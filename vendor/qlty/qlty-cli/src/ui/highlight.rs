use anyhow::{anyhow, Result};
use console::style;
use std::{ops::RangeInclusive, path::Path};
use syntect::easy::HighlightLines;
use syntect::highlighting::{Color, Style, ThemeSet};
use syntect::parsing::SyntaxSet;
use syntect::util::as_24_bit_terminal_escaped;
use termbg::Theme;

pub struct Highlighter {
    highlighted_lines: Vec<String>,
}

impl Highlighter {
    pub fn new(path: &Path) -> Result<Self> {
        let timeout = std::time::Duration::from_millis(50);

        let background = match termbg::rgb(timeout) {
            Ok(rgb) => TermbgToSyntectColorAdapter::adapt_color(rgb),
            Err(_) => Color::BLACK,
        };

        let theme_name = match termbg::theme(timeout) {
            Ok(Theme::Light) => "InspiredGitHub",
            Ok(Theme::Dark) => "base16-eighties.dark",
            Err(_) => "base16-eighties.dark",
        };

        let ps = SyntaxSet::load_defaults_newlines();
        let ts = ThemeSet::load_defaults();

        let file_contents = std::fs::read_to_string(path)
            .map_err(|err| anyhow!("Unable to read file {}: {:?}", path.display(), err))?;

        let syntax = ps
            .find_syntax_for_file(path)
            .unwrap() // for IO errors, you may want to use try!() or another plain text fallback
            .unwrap_or_else(|| ps.find_syntax_plain_text());

        let mut theme = ts.themes[theme_name].clone();
        theme.settings.background = Some(background);

        let mut h = HighlightLines::new(syntax, &theme);

        let mut highlighted_lines = vec![];

        for line in file_contents.lines() {
            let line = format!("{}\n", line);
            let ranges: Vec<(Style, &str)> = h.highlight_line(&line, &ps).unwrap();
            let escaped = as_24_bit_terminal_escaped(&ranges[..], true);
            highlighted_lines.push(escaped);
        }

        Ok(Self { highlighted_lines })
    }

    pub fn print_range(
        &self,
        line_numbers: RangeInclusive<usize>,
        indent_size: usize,
        max_lines: usize,
    ) {
        let start_line = line_numbers.start().to_owned();
        let end_line = line_numbers.end().to_owned();
        let render_end_line = end_line.clamp(start_line, start_line + max_lines - 1);
        let indent = " ".repeat(indent_size);

        for line_number in start_line..=render_end_line {
            let i = line_number - 1;

            let code_string = if i < self.highlighted_lines.len() {
                &self.highlighted_lines[i]
            } else {
                "<~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~>"
            };

            print!(
                "{}{} {}",
                indent,
                style(format!("{:>4} ", line_number)).dim(),
                code_string
            );
        }

        if end_line > render_end_line {
            let missing_lines = end_line - render_end_line;
            println!(
                "{}",
                style(format!(
                    "{}      [hid {} additional lines]",
                    indent, missing_lines
                ))
                .dim()
            );
        }
    }
}

struct TermbgToSyntectColorAdapter;

impl TermbgToSyntectColorAdapter {
    // Convert termbg::Rgb to syntect::highlighting::Color
    pub fn adapt_color(termbg_color: termbg::Rgb) -> syntect::highlighting::Color {
        let r = Self::convert_16bit_to_8bit(termbg_color.r);
        let g = Self::convert_16bit_to_8bit(termbg_color.g);
        let b = Self::convert_16bit_to_8bit(termbg_color.b);

        syntect::highlighting::Color { r, g, b, a: 0xFF }
    }

    // Helper method to convert a single 16-bit value to 8-bit
    fn convert_16bit_to_8bit(color_16bit: u16) -> u8 {
        ((color_16bit as f64 / 65535.0) * 255.0).round() as u8
    }
}
