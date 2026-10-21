use std::process::Child;

/// Owns a child and, on Unix, its dedicated process group until capture ends.
pub(super) struct OwnedProcess {
    pub(super) child: Child,
    terminated: bool,
}

impl OwnedProcess {
    /// On Unix the command must use `process_group(0)` before spawning.
    pub(super) fn new(child: Child) -> Self {
        Self {
            child,
            terminated: false,
        }
    }

    pub(super) fn terminate(&mut self) {
        if self.terminated {
            return;
        }
        self.terminated = true;
        #[cfg(unix)]
        {
            let process_group = self.child.id() as libc::pid_t;
            // SAFETY: the caller created a dedicated group for this invocation.
            // A missing group means its last process already exited.
            unsafe {
                let _ = libc::kill(-process_group, libc::SIGKILL);
            }
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for OwnedProcess {
    fn drop(&mut self) {
        self.terminate();
    }
}
