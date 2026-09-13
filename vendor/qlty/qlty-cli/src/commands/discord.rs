use crate::{errors::CommandError, success::CommandSuccess, Arguments};
use anyhow::Result;
use clap::Args;

#[derive(Args, Debug)]
pub struct Discord {}

impl Discord {
    pub fn execute(&self, _args: &Arguments) -> Result<CommandSuccess, CommandError> {
        webbrowser::open("https://qlty.sh/discord")?;
        CommandSuccess::ok()
    }
}
