# Release v2.2.5

- **Fix 0x49 with firmware < 1.4 always reporting open** - looks like firmware versions
prior to 1.4 send a 0x2C frame after the movement stops without position bytes.