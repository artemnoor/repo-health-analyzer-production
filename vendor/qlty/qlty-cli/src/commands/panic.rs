use crate::{Arguments, CommandError, CommandSuccess};
use anyhow::Result;
use clap::Args;

#[derive(Args, Debug)]
pub struct Panic {}

#[allow(unreachable_code)]
impl Panic {
    pub fn execute(&self, _args: &Arguments) -> Result<CommandSuccess, CommandError> {
        panic!("This is an intentional panic.");
        CommandSuccess::ok()
    }
}
