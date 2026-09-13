use duct::{cmd, Expression};
use itertools::Itertools;
use qlty_analysis::utils::fs::path_to_native_string;
use std::{fmt::Debug, io::Write};
use tempfile::Builder;
use tracing::debug;

#[derive(Debug)]
pub struct Command {
    pub cmd: Expression,
    pub script: String,

    // Used for tracking lifetime of batch file
    #[allow(dead_code)]
    batch_file: Option<tempfile::TempPath>,
}

impl Command {
    pub fn new(builder: Option<Box<dyn CommandBuilder>>, script: impl Into<String>) -> Self {
        if cfg!(windows) {
            Self::new_windows(builder, script)
        } else {
            Self::new_unix(builder, script)
        }
    }

    fn new_windows(builder: Option<Box<dyn CommandBuilder>>, script: impl Into<String>) -> Self {
        let script = script.into();
        let builder = builder.unwrap_or_else(|| default_command_builder());
        let rerun = format!("cmd /c \"{}\"", &script);

        if script.contains('"') {
            let mut batch_file = Builder::new()
                .prefix("qlty-cmd-")
                .suffix(".bat")
                .rand_bytes(5)
                .tempfile()
                .unwrap();
            write!(batch_file, "@echo off\r\n{}\r\n", &script).unwrap();
            let batch_path = batch_file.into_temp_path();
            debug!("Wrote command {:?}: {:?}", &batch_path, &script);

            Command {
                cmd: builder.build(&path_to_native_string(&batch_path), vec![]),
                script: rerun,
                batch_file: Some(batch_path),
            }
        } else {
            Command {
                cmd: builder.build("cmd", vec!["/c", &script]),
                script: rerun,
                batch_file: None,
            }
        }
    }

    fn new_unix(builder: Option<Box<dyn CommandBuilder>>, script: impl Into<String>) -> Self {
        let script = script.into();
        let args = ["sh", "-c", &script];
        let cmd = builder
            .unwrap_or_else(|| default_command_builder())
            .build(args[0], args[1..].to_vec());
        let script = args
            .iter()
            .map(|arg| {
                if arg.contains(' ') {
                    format!(r#""{}""#, arg.replace('\"', r#"\""#))
                } else {
                    arg.to_string()
                }
            })
            .join(" ");

        Command {
            cmd,
            script,
            batch_file: None,
        }
    }
}

pub trait CommandBuilder: Debug + Sync + Send {
    fn build(&self, bin: &str, args: Vec<&str>) -> Expression;
    fn clone_box(&self) -> Box<dyn CommandBuilder>;
}

#[derive(Debug)]
struct DefaultCommandBuilder {}
impl CommandBuilder for DefaultCommandBuilder {
    fn build(&self, bin: &str, args: Vec<&str>) -> Expression {
        cmd(bin, args)
    }

    fn clone_box(&self) -> Box<dyn CommandBuilder> {
        default_command_builder()
    }
}

impl Clone for Box<dyn CommandBuilder> {
    fn clone(&self) -> Self {
        self.clone_box()
    }
}

impl Default for Box<dyn CommandBuilder> {
    fn default() -> Self {
        default_command_builder()
    }
}

pub fn default_command_builder() -> Box<impl CommandBuilder> {
    Box::new(DefaultCommandBuilder {})
}

#[cfg(test)]
pub mod test {
    use super::{default_command_builder, CommandBuilder};
    use crate::{tool::command_builder::Command, Tool};
    use duct::Expression;
    use once_cell::sync::Lazy;
    use std::sync::{Arc, Mutex};
    use tempfile::TempDir;

    pub static ENV_LOCK: Lazy<Mutex<()>> = Lazy::new(Mutex::default);

    pub fn stub_cmd(list: Arc<Mutex<Vec<Vec<String>>>>) -> Box<impl CommandBuilder> {
        #[derive(Debug)]
        struct DefaultCommandBuilder {
            list: Arc<Mutex<Vec<Vec<String>>>>,
        }
        impl CommandBuilder for DefaultCommandBuilder {
            fn build(&self, bin: &str, args: Vec<&str>) -> Expression {
                let mut locked_list = self.list.lock().unwrap();
                let mut pushed_list = vec![];
                pushed_list.push(bin);
                pushed_list.extend(args);
                locked_list.push(pushed_list.iter().map(|s| s.to_string()).collect());

                // need a command that's guaranteed to be in path
                // and shell commands don't count (like echo)
                Command::new(None, "exit 0").cmd
            }

            fn clone_box(&self) -> Box<dyn CommandBuilder> {
                Box::new(DefaultCommandBuilder {
                    list: Arc::clone(&self.list),
                })
            }
        }
        Box::new(DefaultCommandBuilder { list })
    }

    /// Override tools_root() and create necessary cache directories.
    /// Must call this if you modify NodePackage
    /// Make sure you lock using ENV_LOCK before calling this function.
    pub fn reroute_tools_root(temp_path: &TempDir, pkg: &dyn Tool) {
        std::env::set_var("HOME", temp_path.path());
        std::fs::create_dir_all(pkg.directory()).unwrap();
    }

    #[test]
    fn test_default_command_builder() {
        let builder = default_command_builder();
        let cmd = Command::new(Some(builder), "echo success.").cmd;
        assert_eq!(cmd.stdout_capture().read().unwrap(), "success.");
    }

    #[test]
    fn test_default_command_builder_quotes() {
        let builder = default_command_builder();
        let command = Command::new(Some(builder), r#"echo "success with quotes"."#);
        if cfg!(windows) {
            let batch_file = command.batch_file.unwrap();
            assert_eq!(batch_file.extension().unwrap(), "bat");
            assert_eq!(
                std::fs::read_to_string(&batch_file)
                    .expect(&format!("Batch file not found: {:?}", batch_file)),
                "@echo off\r\necho \"success with quotes\".\r\n"
            );
            assert_eq!(
                command.cmd.stdout_capture().read().unwrap(),
                r#""success with quotes"."#
            );
        } else {
            assert_eq!(
                command.cmd.stdout_capture().read().unwrap(),
                "success with quotes."
            );
        }
    }
}
