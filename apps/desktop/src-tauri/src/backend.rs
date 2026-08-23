//! Sidecar lifecycle for the packaged Python backend (PyInstaller onedir).
//!
//! Release builds spawn the bundled `confab-backend` binary in its own
//! process group, read the `CONFAB_PORT=<n>` handshake off its stdout, and
//! kill the whole group on exit — killing only the direct child leaks the
//! bootloader's grandchild uvicorn process (see apps/backend/PACKAGING.md).

use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::net::TcpStream;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Mutex};
use std::time::{Duration, Instant};

/// How long to wait for the `CONFAB_PORT=` announcement before giving up.
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(60);
/// After the handshake, how long to wait for the port to accept connections.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(20);

pub struct Backend {
    child: Mutex<Option<Child>>,
    /// Process-group id (== child pid; spawned with `process_group(0)`).
    pgid: i32,
}

/// Spawn the backend and block until it is reachable. Returns the process
/// handle (manage it as Tauri state so it survives until exit) and the port.
pub fn spawn(resource_dir: &Path, log_dir: &Path) -> Result<(Backend, u16), String> {
    let binary = resource_dir.join("backend/confab-backend/confab-backend");
    if !binary.is_file() {
        return Err(format!("backend binary missing at {}", binary.display()));
    }

    std::fs::create_dir_all(log_dir).map_err(|e| format!("cannot create log dir: {e}"))?;
    let log_path = log_dir.join("backend.log");
    let log = File::create(&log_path).map_err(|e| format!("cannot open backend log: {e}"))?;
    let stderr_log = log.try_clone().map_err(|e| format!("cannot clone log handle: {e}"))?;

    let mut child = Command::new(&binary)
        .stdout(Stdio::piped())
        .stderr(Stdio::from(stderr_log)) // uvicorn logs on stderr → straight to file
        .process_group(0)
        .spawn()
        .map_err(|e| format!("cannot spawn {}: {e}", binary.display()))?;
    let pgid = child.id() as i32;
    let stdout = child.stdout.take().expect("stdout was piped");

    // Reader thread: find the handshake, then keep draining stdout into the
    // log file so the pipe never fills up and blocks the backend.
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut log = log;
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else { break };
            let _ = writeln!(log, "{line}");
            if let Some(port) = line.strip_prefix("CONFAB_PORT=") {
                let _ = tx.send(port.trim().parse::<u16>());
            }
        }
    });

    let port = match rx.recv_timeout(HANDSHAKE_TIMEOUT) {
        Ok(Ok(port)) => port,
        Ok(Err(e)) => return Err(format!("unparseable port in handshake: {e}")),
        Err(_) => {
            // Timed out or the process died (channel disconnected) — either
            // way the backend is not coming up.
            return Err(format!(
                "no CONFAB_PORT handshake from the backend — see {}",
                log_path.display()
            ));
        }
    };

    // The handshake prints before uvicorn binds; wait until it accepts.
    let deadline = Instant::now() + CONNECT_TIMEOUT;
    loop {
        match TcpStream::connect(("127.0.0.1", port)) {
            Ok(_) => break,
            Err(_) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(100)),
            Err(e) => return Err(format!("backend port {port} never accepted connections: {e}")),
        }
    }

    Ok((
        Backend {
            child: Mutex::new(Some(child)),
            pgid,
        },
        port,
    ))
}

impl Backend {
    /// SIGTERM the whole process group (uvicorn shuts down gracefully),
    /// escalating to SIGKILL if it lingers.
    pub fn shutdown(&self) {
        let Some(mut child) = self.child.lock().unwrap().take() else {
            return;
        };
        unsafe { libc::kill(-self.pgid, libc::SIGTERM) };
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            match child.try_wait() {
                Ok(Some(_)) => break,
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(50))
                }
                _ => {
                    unsafe { libc::kill(-self.pgid, libc::SIGKILL) };
                    let _ = child.wait();
                    break;
                }
            }
        }
    }
}
