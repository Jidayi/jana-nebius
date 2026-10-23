//! The per-launch bearer token (API-02): 256 random bits, made by the shell for each core process, given to the core
//! over its stdin and to the webview through a command; never in argv, the environment, a file or a log.

use std::fmt;

#[derive(Clone, PartialEq, Eq)]
pub struct Token(String);

impl Token {
    pub fn new() -> Self {
        let mut bytes = [0u8; 32];
        getrandom::fill(&mut bytes).expect("the operating system's random source is available");
        Token(bytes.iter().map(|b| format!("{b:02x}")).collect())
    }

    pub fn reveal(&self) -> &str {
        &self.0
    }
}

impl Default for Token {
    fn default() -> Self {
        Self::new()
    }
}

/// A token never prints: logs and panics show a placeholder.
impl fmt::Debug for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Token(<redacted>)")
    }
}

#[cfg(test)]
mod tests {
    use super::Token;

    #[test]
    fn tokens_are_256_bit_and_never_printed() {
        let a = Token::new();
        let b = Token::new();
        assert_eq!(a.reveal().len(), 64);
        assert_ne!(a, b);
        assert_eq!(format!("{a:?}"), "Token(<redacted>)");
    }
}
