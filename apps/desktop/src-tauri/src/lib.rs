mod backend;

use std::path::{Path, PathBuf};

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl};
use tauri::webview::{DownloadEvent, WebviewWindowBuilder};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
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

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            if let Some(backend) = app.try_state::<backend::Backend>() {
                backend.shutdown();
            }
        }
    });
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
                    .map(|name| PathBuf::from(name))
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
