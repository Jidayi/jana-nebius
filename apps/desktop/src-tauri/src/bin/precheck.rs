//! `jana-precheck --needed-bytes N --free-bytes F [--lang L] [--message-file PATH]`: the installer's checks before
//! copying (PLT-01, PLT-06, PLT-29).
//!
//! The NSIS and MSI hooks extract this program to the installer's temporary folder and run it with the size of the
//! app plus the selected packs, the free space on the target drive and the installer's language (a Windows language
//! id or a locale name; English when absent). It prints the message to show (if any) in that language's words from
//! the installers' catalogue (LOC-01), also writes it as UTF-16LE to `--message-file` for NSIS, and exits 0 to install
//! (with a below-the-minimum notice when there is one) or 2 to stop before copying.

use jana_shell::installer::{locale_for, precheck, this_os, this_ram_bytes, utf16le};

fn option<'a>(args: &'a [String], name: &str) -> Option<&'a str> {
    let at = args.iter().position(|a| a == name)?;
    args.get(at + 1).map(String::as_str)
}

fn value(args: &[String], name: &str) -> Option<u64> {
    option(args, name)?.parse().ok()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    // The MSI passes free space in 512-byte units (PrimaryVolumeSpaceAvailable); NSIS passes bytes.
    let free = value(&args, "--free-bytes")
        .or_else(|| value(&args, "--free-blocks512").map(|blocks| blocks.saturating_mul(512)));
    let (Some(needed), Some(free)) = (value(&args, "--needed-bytes"), free) else {
        eprintln!(
            "usage: jana-precheck --needed-bytes N (--free-bytes F | --free-blocks512 B) [--lang L] \
             [--message-file PATH]"
        );
        std::process::exit(64);
    };
    let locale = locale_for(option(&args, "--lang"));
    let outcome = precheck(&this_os(), needed, free, this_ram_bytes());
    let text = outcome.text(locale).unwrap_or_default();
    if !text.is_empty() {
        println!("{text}");
    }
    if let Some(path) = option(&args, "--message-file") {
        // Written even when empty, so a file left from an earlier run never shows.
        if std::fs::write(path, utf16le(&text)).is_err() {
            eprintln!("jana-precheck: could not write the message file");
        }
    }
    std::process::exit(outcome.exit_code());
}
