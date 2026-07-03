# Entity Dictionary

Single source of truth for all runtime entity definitions in W4P.

Every other document references this one. No entity is redefined elsewhere.

---

## Core Entities

### Session

A continuous period of observation by the W4P platform. Begins when the Chrome Extension connects to a GoldRush Poker table and begins sending snapshots. Ends when the extension disconnects or the table is closed.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `session_id` | TEXT | Stable | Unique identifier for the observation session |
| `table_id` | TEXT | Stable | Which table is being observed |
| `started_at` | TEXT | Stable | ISO 8601 timestamp of first snapshot |
| `ended_at` | TEXT | Stable | ISO 8601 timestamp of last snapshot (null if ongoing) |
| `git_sha` | TEXT | Stable | Code version at session start |

Relationships:
- One Session observes one Table
- One Session contains many Hands
- One Session produces many Snapshots

---

### Table

A poker table in the GoldRush Poker client. The physical or virtual surface where the game is played.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `table_id` | TEXT | Stable | Unique identifier for the table |
| `table_name` | TEXT | Stable | Human-readable table name (e.g. "Lagos 1") |
| `max_seats` | INTEGER | Stable | Maximum number of seats at this table |
| `game_type` | TEXT | Stable | e.g. "PLO", "NLHE" |
| `stakes` | TEXT | Stable | e.g. "5/10", "1/2" |

Relationships:
- One Table is observed by many Sessions
- One Table contains many Seats
- One Table hosts many Hands

---

### Hand

A single deal of cards, from the first card dealt to showdown or the last player folding. The fundamental unit of poker gameplay.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `hand_id` | TEXT | Stable | Unique identifier (if provided by GoldRush) |
| `table_id` | TEXT | Stable | Which table this hand was played on |
| `session_id` | TEXT | Stable | Which observation session captured this hand |
| `hand_number` | INTEGER | Stable | Sequential hand number within the session |
| `started_at` | TEXT | Stable | ISO 8601 of first deal action |
| `ended_at` | TEXT | Stable | ISO 8601 of pot awarded or last fold |

Relationships:
- One Hand belongs to one Table
- One Hand belongs to one Session
- One Hand progresses through many Streets
- One Hand involves many Players (via Seats)
- One Hand has one Board
- One Hand has one Pot

---

### Street

A phase within a Hand. Represents a dealing round and the subsequent betting round.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `hand_id` | TEXT | Stable | Which hand this street belongs to |
| `name` | TEXT | Stable | Preflop / Flop / Turn / River / Showdown |
| `cards_dealt` | TEXT | Stable | Which cards were dealt at the start of this street |
| `started_at` | TEXT | Stable | ISO 8601 |

Ordering is fixed: Preflop → Flop → Turn → River → Showdown.

Relationships:
- One Street belongs to one Hand
- One Street contains many Actions
- One Street may deal cards to the Board (Flop, Turn, River)

---

### Board

The community cards shared by all active players. Dealt progressively across streets.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `hand_id` | TEXT | Stable | Which hand this board belongs to |
| `cards` | TEXT | Volatile | JSON array of card strings, grows per street |
| `flop` | TEXT | Stable | First three community cards (null until Flop) |
| `turn` | TEXT | Stable | Fourth community card (null until Turn) |
| `river` | TEXT | Stable | Fifth community card (null until River) |

Relationships:
- One Board belongs to one Hand
- Board cards are revealed progressively across Streets

---

### Pot

The total chips being contested in the current Hand.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `hand_id` | TEXT | Stable | Which hand this pot belongs to |
| `total` | REAL | Volatile | Total chips in the pot (grows through the hand) |
| `side_pots` | TEXT | Volatile | JSON array of side pot amounts (if any) |

Relationships:
- One Pot belongs to one Hand
- Pot size is monotonically increasing within a Hand

---

### Seat

A position at the Table. A fixed index that a Player occupies during a Hand or Session.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `seat_index` | INTEGER | Stable | Position number (table-specific numbering) |
| `table_id` | TEXT | Stable | Which table this seat belongs to |
| `player_name` | TEXT | Mostly Stable | Which player currently occupies this seat |
| `is_occupied` | INTEGER | Volatile | 1 if a player is sitting here |
| `is_active` | INTEGER | Volatile | 1 if the player is active in the current hand |

The seat index is stable within a table — seat 3 is always the same physical position. The player occupying it may change.

Relationships:
- One Seat belongs to one Table
- One Seat is occupied by zero or one Player at any time
- One Seat is identified as the Dealer for a given Hand
- One Seat may be the Hero seat

---

### Player

A named participant with a chip stack. Identified by their display name in GoldRush Poker.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `player_name` | TEXT | Mostly Stable | Display name (may change between sessions) |
| `player_id` | TEXT | Unknown | Whether GoldRush provides a persistent player ID |
| `is_hero` | INTEGER | Mostly Stable | 1 if this player is the hero (the account being observed) |

Player names are mostly stable but may change if a player changes their display name.

Relationships:
- One Player occupies one Seat at a time (in a given Hand)
- One Player has one Stack at a time
- One Player performs many Actions
- One Player may be the Bot (if automated)
- One Player may be the Hero

---

### Stack

A Player's chip count at a point in time.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `player_name` | TEXT | Mostly Stable | Which player this stack belongs to |
| `seat_index` | INTEGER | Stable | Which seat this stack is at |
| `amount` | REAL | Volatile | Chip count (changes with every action) |
| `snapshot_seq` | INTEGER | Stable | Which snapshot this stack was observed in |

Relationships:
- One Stack belongs to one Player at one point in time
- Stack amount changes with every bet, call, raise, win, or loss

---

### Bot

An automated player controlled by the W4P platform. The Bot may be the Hero or a separate entity.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `bot_id` | TEXT | Stable | Unique identifier for the bot instance |
| `player_name` | TEXT | Mostly Stable | Which player name the bot plays under |
| `is_hero` | INTEGER | Stable | Whether the bot is the hero |
| `strategy` | TEXT | Mostly Stable | Which strategy the bot is executing |

Relationships:
- One Bot is associated with one Player
- One Bot may be the Hero
- One Bot issues Commands that become Actions

---

### Action

A player decision during a Hand. Observed from the runtime.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `hand_id` | TEXT | Stable | Which hand |
| `street` | TEXT | Stable | Which street |
| `player_name` | TEXT | Mostly Stable | Who acted |
| `seat_index` | INTEGER | Stable | From which seat |
| `action_type` | TEXT | Stable | fold / check / call / bet / raise |
| `amount` | REAL | Volatile | Bet/raise amount (null for fold/check/call) |
| `is_hero_action` | INTEGER | Stable | 1 if this was the hero's action |
| `snapshot_seq` | INTEGER | Stable | Which snapshot captured this action |

Relationships:
- One Action belongs to one Hand and one Street
- One Action is performed by one Player from one Seat
- One Action changes the Pot and the acting Player's Stack

---

### Command

An instruction issued to the Bot. A Command may become an Action if executed, or may be rejected/ignored.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `command_id` | TEXT | Stable | Unique identifier |
| `issued_at` | TEXT | Stable | ISO 8601 timestamp |
| `command_type` | TEXT | Stable | fold / check / call / bet / raise |
| `amount` | REAL | Volatile | Bet/raise amount |
| `status` | TEXT | Volatile | pending / executed / rejected / expired |
| `resulting_action` | TEXT | Volatile | FK to Action (if executed) |

Relationships:
- One Command may result in one Action
- One Command is issued to one Bot

---

### Cash-out

A Player leaving the Table and collecting their chips.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `player_name` | TEXT | Mostly Stable | Who left |
| `seat_index` | INTEGER | Stable | Which seat was vacated |
| `final_stack` | REAL | Stable | Stack size at departure |
| `snapshot_seq` | INTEGER | Stable | Which snapshot captured the departure |
| `timestamp` | TEXT | Stable | ISO 8601 |

Relationships:
- One Cash-out ends a Player's occupation of a Seat

---

## Observation Entities

### Snapshot

A point-in-time capture of the runtime state. The fundamental unit of observation. One POST to `/api/snapshot` produces one Snapshot.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `snapshot_seq` | INTEGER | Stable | Monotonic global sequence number |
| `hand_epoch` | INTEGER | Stable | Intra-hand counter, resets to 0 per hand |
| `timestamp` | TEXT | Stable | ISO 8601 with timezone |
| `table_id` | TEXT | Stable | Which table |
| `hand_id` | TEXT | Mostly Stable | Which hand (null between hands) |
| `provenance` | TEXT | Stable | Source metadata (layer, component, git_sha, container, build) |

Relationships:
- One Snapshot belongs to one Session
- One Snapshot captures state for one Table
- One Snapshot contains many Observations
- One Snapshot may capture zero or more Anomalies

---

### Observation

A single field value captured within a Snapshot, with its provenance.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `id` | INTEGER | Stable | Auto-increment PK |
| `snapshot_seq` | INTEGER | Stable | FK to Snapshot |
| `field_name` | TEXT | Stable | Which field (e.g. `hole_cards`, `player_name`) |
| `field_value` | TEXT | Volatile | The observed value |
| `layer` | TEXT | Stable | extension / flask / api / remote_ui / engine_ui |
| `component` | TEXT | Stable | Specific file or module |
| `git_sha` | TEXT | Stable | Commit hash of running code |
| `container` | TEXT | Stable | Which container/process |
| `build` | TEXT | Stable | runtime / debug / release |

Relationships:
- One Observation belongs to one Snapshot
- One Observation captures one field value from one layer

---

### Correlation

A measured relationship between two entities, backed by observations. Not assumed — derived from data.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `id` | INTEGER | Stable | Auto-increment PK |
| `relationship` | TEXT | Stable | Human-readable description |
| `confidence` | REAL | Volatile | 0.0 to 1.0, updated as more data arrives |
| `first_observed` | TEXT | Stable | ISO 8601 of first confirming observation |
| `last_observed` | TEXT | Stable | ISO 8601 of most recent confirming observation |
| `observation_count` | INTEGER | Volatile | Grows with each confirming observation |
| `contradiction_count` | INTEGER | Volatile | Grows with each contradicting observation |
| `evidence_sources` | TEXT | Stable | JSON array of layers that confirmed it |
| `git_sha_range` | TEXT | Stable | Code versions this was observed under |

Relationships:
- One Correlation is supported by many Observations
- One Correlation may be contradicted by some Observations

---

### Anomaly

An observation that contradicts expectations. Recorded without diagnosis.

| Attribute | Type | Stability | Description |
|---|---|---|---|
| `id` | INTEGER | Stable | Auto-increment PK |
| `snapshot_seq` | INTEGER | Stable | Where it was observed |
| `timestamp` | TEXT | Stable | ISO 8601 |
| `hand_epoch` | INTEGER | Stable | Intra-hand position |
| `table_id` | TEXT | Stable | Which table |
| `anomaly_type` | TEXT | Stable | Short category label |
| `observed` | TEXT | Stable | Verbatim field values |
| `expected` | TEXT | Stable | What would have been expected |
| `frequency` | TEXT | Volatile | Updated as more instances are found |
| `source_layer` | TEXT | Stable | Which layer produced the anomalous value |
| `source_component` | TEXT | Stable | Which component |
| `git_sha` | TEXT | Stable | Code version at time of anomaly |
| `conclusion` | TEXT | Volatile | "No conclusion drawn" unless independently verified |

---

## Entity Relationship Summary

```
Session ──► Table
  │
  └──► Hand ──► Street ──► Action
          │          │
          │          └──► Board
          │
          ├──► Pot
          │
          └──► Seat ◄── Player ◄── Bot
                 │          │
                 │          ├──► Stack
                 │          │
                 │          └──► Command
                 │
                 └──► Cash-out

Snapshot ──► Observation
  │
  ├──► Correlation
  │
  └──► Anomaly
```

---

## Naming Conventions

- Entity names are **PascalCase**: `Hand`, `Player`, `Seat`
- Table names are **snake_case**: `snapshots`, `correlations`, `anomalies`
- Field names are **snake_case**: `snapshot_seq`, `player_name`, `hole_cards`
- JSON fields preserve their runtime naming: `players_json`, `available_actions`
- Provenance fields use **snake_case**: `source_layer`, `git_sha`
