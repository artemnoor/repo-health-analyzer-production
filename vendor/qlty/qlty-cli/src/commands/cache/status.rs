use crate::{Arguments, CommandError, CommandSuccess};
use anyhow::Result;
use bytesize::ByteSize;
use clap::Args;
use cli_table::{
    format::{Border, HorizontalLine, Justify, Separator, VerticalLine},
    print_stdout, Cell, Table,
};
use qlty_config::Workspace;

#[derive(Args, Debug)]
pub struct Status {}

impl Status {
    pub fn execute(&self, _args: &Arguments) -> Result<CommandSuccess, CommandError> {
        let workspace = Workspace::new()?;
        let library = workspace.library()?;
        let folder_statuses = library.status()?;

        let rows = folder_statuses
            .iter()
            .map(|status| {
                vec![
                    status
                        .dir
                        .to_string_lossy()
                        .to_string()
                        .cell()
                        .justify(Justify::Left),
                    format!("{}", status.files_count)
                        .cell()
                        .justify(Justify::Right),
                    ByteSize(status.files_bytes)
                        .to_string_as(true)
                        .cell()
                        .justify(Justify::Right),
                ]
            })
            .collect::<Vec<_>>();

        let table = rows
            .table()
            .title(vec![
                "Path".cell(),
                "Files".cell().justify(Justify::Right),
                "Bytes".cell().justify(Justify::Right),
            ])
            .border(Border::builder().build())
            .separator(
                Separator::builder()
                    .title(Some(HorizontalLine::default()))
                    .column(Some(VerticalLine::default()))
                    .build(),
            );
        print_stdout(table)?;

        CommandSuccess::ok()
    }
}
