//! Task-local verification kits are inputs even when controller artifacts are ignored.

use crate::bounded_fs::{self, BoundedPathKind, ReadControl, RootCapability};
use crate::spec::{ParsedSpec, VerifyEntry};
use std::collections::BTreeSet;
use std::path::Path;

const MAX_KIT_ENTRIES: usize = 1024;

pub(crate) fn paths(
    root: &RootCapability,
    spec: &ParsedSpec,
    control: ReadControl<'_>,
) -> Result<BTreeSet<String>, String> {
    let mut inputs = BTreeSet::new();
    for entry in spec.frontmatter.iter().flat_map(|fm| &fm.verify) {
        if let VerifyEntry::Observed { run, .. } = entry {
            inputs.extend(run.inputs.iter().cloned());
        }
    }
    let relative = root
        .repository_relative(Path::new(&spec.path))
        .map_err(|_| "verification_input_spec_path_invalid")?;
    let kit = relative
        .parent()
        .ok_or("verification_input_spec_path_invalid")?
        .join("verify");
    let mut pending = vec![kit];
    let mut entries = 0;
    while let Some(relative) = pending.pop() {
        let path = root.requested_root().join(&relative);
        match bounded_fs::inspect_path_kind_with_capability(root, &path, control) {
            Ok(BoundedPathKind::RegularFile) => {
                inputs.insert(
                    bounded_fs::normalize_repository_relative_path(&relative)
                        .map_err(|_| "verification_input_path_invalid")?,
                );
            }
            Ok(BoundedPathKind::Directory) => {
                let names = bounded_fs::read_directory_names_with_capability(
                    root,
                    &path,
                    MAX_KIT_ENTRIES.saturating_sub(entries),
                    control,
                )
                .map_err(|_| "verification_kit_unavailable")?;
                entries += names.len();
                pending.extend(names.into_iter().map(|name| relative.join(name)));
            }
            Err(bounded_fs::BoundedReadError::Io(error))
                if error.kind() == std::io::ErrorKind::NotFound && entries == 0 => {}
            _ => return Err("verification_kit_unavailable".into()),
        }
    }
    Ok(inputs)
}
