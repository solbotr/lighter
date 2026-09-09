# Market-maker deployment

The watchdog starts the sniper normally and opts the market maker in with `MM_ENABLED=1`.
Configure `LIGHTER_MM_ACCOUNT_INDEX` to a dedicated **Standard-tier subaccount**, plus
`LIGHTER_MM_API_KEY_INDEX`, `LIGHTER_MM_API_PRIVATE_KEY`, `LIGHTER_MM_ASSET`,
`MARKET_INDEX`, `BASE_ORDER_SIZE`, and `TARGET_SPREAD_BPS`. `NUM_LAYERS` defaults to 3;
`LIGHTER_MM_DB_PATH` optionally selects its SQLite file. MM Telegram polling is off by
default; set `MM_ENABLE_TELEGRAM=1` only when it uses a token that is not already polled.

Standard tier is required for truly fee-free quoting (0 maker / 0 taker, 300 ms).
Premium costs 0.4 bps maker / 2.8 bps taker (200 ms). Tiers belong to the L1
address/subaccount; switch the MM subaccount with `changeAccountTier` before deployment
(the bot does not switch it).

Creating `lighter_kill_switch.flag` halts the MM. For roughly $700 total capital, a
conservative start is $250–300 on the MM subaccount, 1–2 markets, 3 layers, and about
$15–20 notional per layer, keeping maximum inventory below roughly $150.
