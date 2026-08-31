mod backend;

use std::path::{Path, PathBuf};

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::webview::{DownloadEvent, WebviewWindowBuilder};
use tauri::{AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WindowEvent, Wry};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

/// System-wide record toggle (also shown in the tray menu).
const HOTKEY: &str = "super+shift+r";

/// Tray handles kept in state so `set_recording` can update the menu label.
struct Tray {
    toggle: MenuItem<Wry>,
}

#[tauri::command]
fn set_recording(app: AppHandle, recording: bool) {
    if let Some(tray) = app.try_state::<Tray>() {
        let label = if recording { "Stop Recording" } else { "Start Recording" };
        let _ = tray.toggle.set_text(label);
    }
}

/// Fully restart Confab — kills the app (and its backend sidecar, via the
/// RunEvent::Exit → process-group kill) and relaunches. Used after switching
/// transcription engine, so the new model loads in a clean process.
#[tauri::command]
fn restart_app(app: AppHandle) {
    app.restart();
}

/// A meeting was detected: bring Confab forward (even from the tray) and post
/// a native notification, so the prompt is seen no matter where the user is.
#[tauri::command]
fn meeting_alert(app: AppHandle, title: String, body: String, focus: bool) {
    use tauri_plugin_notification::NotificationExt;

    if focus {
        show_main_window(&app);
    }
    let _ = app
        .notification()
        .builder()
        .title(title)
        .body(body)
        .show();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        let _ = app.emit("toggle-record", ());
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            set_recording,
            meeting_alert,
            restart_app
        ])
        .on_window_event(|window, event| {
            // macOS convention: closing the window keeps the app (and any
            // recording) alive in the tray; Cmd-Q / tray Quit really quits.
            if let WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .setup(|app| {
            setup_tray(app.handle())?;
            if let Err(error) = app.global_shortcut().register(HOTKEY) {
                // Another app may own the combo — the tray still works.
                eprintln!("global shortcut unavailable: {error}");
            }
            if cfg!(debug_assertions) {
                // Dev: ./launch.sh runs the backend on the fixed dev port
                // (config.ts falls back to 8765 when no port is injected).
                create_main_window(app.handle(), None)?;
            } else {
                spawn_backend_then_window(app.handle().clone());
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app, event| match event {
        RunEvent::Exit => {
            if let Some(backend) = app.try_state::<backend::Backend>() {
                backend.shutdown();
            }
        }
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => show_main_window(app),
        _ => {}
    });
}

fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    let toggle = MenuItem::with_id(app, "toggle-record", "Start Recording", true, None::<&str>)?;
    let show = MenuItem::with_id(app, "show", "Show Confab", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Confab", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&toggle, &show, &quit])?;

    let icon = Image::from_bytes(include_bytes!("../icons/tray.png"))?;
    TrayIconBuilder::with_id("main-tray")
        .icon(icon)
        .icon_as_template(true)
        .tooltip("Confab")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "toggle-record" => {
                let _ = app.emit("toggle-record", ());
            }
            "show" => show_main_window(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;

    app.manage(Tray { toggle });
    Ok(())
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// Release path: bring the sidecar up off the main thread (cold start is
/// ~2–3 s), then open the window with the announced port injected so the
/// frontend reads it before its module graph loads.
fn spawn_backend_then_window(handle: AppHandle) {
    std::thread::spawn(move || {
        let resource_dir = handle
            .path()
            .resource_dir()
            .expect("app bundle has a resource dir");
        let log_dir = handle
            .path()
            .app_log_dir()
            .unwrap_or_else(|_| std::env::temp_dir());

        let port = match backend::spawn(&resource_dir, &log_dir) {
            Ok((process, port)) => {
                handle.manage(process);
                Some(port)
            }
            Err(error) => {
                // Open the window anyway: the frontend's health check fails
                // against the fallback port and surfaces an error toast,
                // which beats a silently missing window.
                eprintln!("backend failed to start: {error}");
                None
            }
        };

        let on_main = handle.clone();
        let _ = handle.run_on_main_thread(move || {
            create_main_window(&on_main, port).expect("main window creation failed");
        });
    });
}

fn create_main_window(app: &AppHandle, port: Option<u16>) -> tauri::Result<()> {
    let mut builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
        .title("Confab")
        .inner_size(1100.0, 720.0)
        .min_inner_size(800.0, 560.0);

    if let Some(port) = port {
        // Must run before the frontend bundle: config.ts reads the port at
        // module-import time.
        builder = builder.initialization_script(format!("window.__CONFAB_PORT__ = {port};"));
    }

    // WKWebView drops <a download> clicks unless a download handler routes
    // them somewhere — send exports to ~/Downloads (collision-safe).
    let downloads_dir = app.path().download_dir().ok();
    builder = builder.on_download(move |_webview, event| {
        if let DownloadEvent::Requested { destination, .. } = event {
            if let Some(dir) = &downloads_dir {
                let suggested = destination
                    .file_name()
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("export"));
                *destination = unique_path(dir, &suggested);
            }
        }
        true
    });

    builder.build()?;
    Ok(())
}

/// `report.pdf` → `report 1.pdf` → `report 2.pdf` … until unused.
fn unique_path(dir: &Path, name: &Path) -> PathBuf {
    let stem = name
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("export");
    let extension = name.extension().and_then(|s| s.to_str());
    let mut candidate = dir.join(name);
    let mut counter = 1;
    while candidate.exists() {
        let file = match extension {
            Some(ext) => format!("{stem} {counter}.{ext}"),
            None => format!("{stem} {counter}"),
        };
        candidate = dir.join(file);
        counter += 1;
    }
    candidate
}
