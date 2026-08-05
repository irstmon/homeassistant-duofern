# Release v2.3.5

- **Fixed:** switches on channel-carrying devices (`0x43` channels, `0x65`/`0x74` channel "01") could briefly show the wrong on/off state right after being toggled — the optimistic state update looked them up the wrong way. Same bug class as the v2.3.4 cover fix, now closed for switches too.
