use crate::{Arguments, CommandError, CommandSuccess};
use anyhow::Result;
use clap::Args;

#[derive(Args, Debug)]
pub struct Signup {}

impl Signup {
    pub fn execute(&self, _args: &Arguments) -> Result<CommandSuccess, CommandError> {
        webbrowser::open("https://qlty.sh/signup")?;
        CommandSuccess::ok()
    }
}
