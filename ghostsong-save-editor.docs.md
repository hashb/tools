Check a Ghost Song `SaveData` file locally for achievement progress, missing healing cores, modules and alternate weapons. The overview suggests where to go next; all 42 achievement goals have guidance and save evidence. Includes locations for 40 modules, 9 weapons and 8 healing-core sources in Steam build 1.2.12d. Optional editing retains the original filename and byte-preserving safety checks.

Open `ghostsong-save-editor.html` directly or serve it as a static page. Import the game's BinaryFormatter `SaveData` and select a slot. Everything runs locally without uploading the save, contacting Steam, or loading external assets. Use **Achievements**, **Collectibles** and **Pasha** to inspect progress. Search names/locations, filter unfinished goals or missing items, and expand individual evidence. A downloadable JSON progress report contains the selected slot's interpreted checklist and whether it includes pending edits. It is a report, not a game save.

Editing is **off by default**, including controls in the raw tree. Turn on **Enable save editing** to change resources, stats or module ownership. Equip granted modules in-game; the ownership editor does not change equipment, power load or weapon bookkeeping, and cannot remove a currently equipped module. Turning editing off keeps pending edits and displays their preview warning. Loading another file returns to read-only mode. Original backup downloads always contain the original bytes. No personal save or proprietary assets are included in this tool.

## What the progress means

**Condition met** is selected-slot evidence, not confirmation that a platform achievement was awarded. Some checks only run on a pickup, conversation, level-up or ending. **In progress** means a saved counter/flag has not reached its target. **Unknown** means the required fields are absent, the state is temporary, or the exact interaction cannot be proven. **Run requirement failed** means the current saved deaths, timer or difficulty fail that run's requirement; it says nothing about previous unlocks.

`achievementslist` is shared across slots. Positive entries are displayed separately as **Unlock recorded · shared**, never used to mark the selected slot's conditions complete. Zero entries are not evidence of locked Steam achievements. The app does not query or alter Steam achievement state. Unknown counters are never silently treated as zero. List access honors `_size` rather than spare backing-array capacity.

The 1.2.12d native checks have older collection targets despite the added content:

| Goal | Native target | Complete current collection |
| --- | --- | --- |
| Fully Equipped | At least 39 acquired modules | 40 visible modules |
| Readiness | At least 8 owned collectible alternate weapons | 9, including Kinzy Axe |
| Feeling Healthy | At least 7 cores in inventory | 8 separate world/shop sources |

The Heartbreaker is blaster slot 2 on-screen, before Scatterburst and Chill Crumbler. Hidden prototype blasters (`wm` indices 6, 8, 10, 16, 17) and the dummy equipped entry 18 are excluded. The actual Skab Device ownership index is **7**, not the prototype index 8. Kinzy Axe belongs to **Toler-Under-Foot**, not Ekman's Crossing; its scene is reached via `ed3 → ed6 → ed7 → ed8`.

Healing-core **inventory** and **source collection** remain separate. Starting/carry-over inventory or New Game Plus resets can make them disagree. The app never guesses a missing core from the total alone. Pickup flags concern the current saved world and are not an account-wide collection history.

| Core source | Read-only evidence | Location |
| --- | --- | --- |
| Belle | `itempickupsvalue[1] > 0` | Lupoto, `dp3b` |
| Pond bot | `miscworldstate[1] > 0` | Lupoto, `dp9`, beyond the Motivator route |
| Huttle Drop | `itempickupsvalue[6] > 0` | `ed3`, east of the Big Bot |
| Beta entrance | `itempickupsvalue[24] > 0` | `rdb1`, upper-left |
| Beta left branch | `itempickupsvalue[30] > 0` | `rdb2b`, branch west of the descent |
| Junkpit hidden chamber | `itempickupsvalue[67] > 0` | `jps4` |
| Sap-Stone | `itempickupsvalue[79] > 0` | `saps1` |
| Bill's core | `billstock[9] == 0` | Crash Site, 2,000 Nanogel after two deliveries |

Bill's initial core stock is 1; only stock 0 is interpreted as purchased. Negative/unlimited/disabled stock and unexpected values remain unknown. The pond bot uses `corebotpickup.DataNumber`, not a SparklyItem pickup flag, and must be checked separately.

The nine weapon ownership indices are `inventory[1,11,12,26,32,33,34,35,68]`: Blast Shield, Hypersledge, Hulking Fist, Dolly, Painwheel, Hazard Blade, Hudson Goodshot, Magma Spear and Kinzy Axe. Hudson Goodshot's serialized internal name is `Goldglum` / `gilisgun`; the English UI name is verified in `UItexty.processlanguage`. The starting melee attack is not one of these nine.

## Achievement evidence

Every row has an in-app explanation and next action. The native achievement IDs map to the shared list in this order: `prog01..09`, `en01..08`, `exp01..05`, `npc01..09`, `com01..03`, `misc01..08` (42 entries).

| Goals | Selected-slot interpretation |
| --- | --- |
| You're Not Alone | `miscworldstate[9] > 0` |
| Part One–Five, Ready To Fly | Valid saved day 1–6 implies 0–5 returned parts |
| Please Sit Down | Ending flag is positive evidence; otherwise final-fight completion remains unknown |
| Safely Away | `finishedgame == true` |
| Crusher, Learned Hunter, Changed One, Ogre, Old Singer, Cracked Engineer, Poet, Red Blob | `minibossvalue[11,9,15,4,10,13,3,17] > 0`, respectively |
| Fully Equipped, Readiness, Feeling Healthy | Counts above |
| Big Bots | Six `bbicons` entries **0,1,2,3,5,6** equal 1; unused index 4 cannot substitute |
| The Cut Machine | Scientist flag 58 shown as context; the exit award itself remains unknown |
| Familiar | `miscworldstate[64] > 0` |
| Charley | Nearby self-talk flag 54 shown as context, not proof of the interaction award |
| Clawing At The Roots Of A Cosmic Order | At least 8 `saymundprogress` entries >= 2 |
| Retired Explorer | Hammer pickup 81 shown as context, not proof of the farewell trigger |
| Good Friends | Bill progress[5] >= 2, Pasha[9] >= 2, Raven[4] >= 2, Molly[5] >= 3 and `inventory[46] > 0` (Work Horse); each requirement is exposed |
| Slow Down, It Was An Accident, Molly The Artist, Voice From The Elevator | `miscworldstate[46,35,44,18] > 0`, respectively |
| Many Enemies | `enemieskilled >= 1000` |
| Feeling Better | `timeshealed >= 100` |
| Bug Slayer | Local pit-spawner counter reaches 34; no persistent progress counter. Total kills cannot substitute |
| Party Trick, Flower Girl, Very Important | Runtime juggle/reaction/position conditions; no reconstructed percentage |
| Hardened | Finished game and `difficulty == 1` (Original; 0 is Explorer) |
| You Monster! | `otherdata[36] >= 12` |
| Maybe It Was Too Easy | Finished game and `timesdied == 0` |
| Experienced | Native `status.LevelUp` compares saved `socketsmax >= 30`. UI explicitly calls this the maximum module-power check, rather than inventing a separate suit-level field |
| Make Haste | Finished game and `timeplayed <= 10800` seconds; display the actual timer and ending requirement |

New Game Plus can carry deaths, time and inventory forward. The app uses the actual saved counters, not an assumed fresh run. Editing is not an achievement unlocker: satisfying a displayed comparison does not prove that the game ran its award routine.

## Verification and sources

The primary evidence is read-only inspection of the supplied **1.2.12d** Unity assets and IL2CPP `GameAssembly.dll`. Decoded types include `modulescript`, `status`, `worlddata`, `npcvendordata`, `SparklyItem`, `corebotpickup`, `roomdata`, `doorway`, NPC spawners and `AchievementData`. Each collectible's scene/shop/pickup reference is embedded beside its location. Asset placement, native checks and English UI initialization take precedence over older guide counts and internal prototype names.

Useful native entry points (Windows image virtual addresses, build-specific):

- `status.GainModule` **0x1803621e0**: module count compared with 39 before `exp01`.
- `status.checkallweapons` **0x180374260** and `status.GainItem` **0x180361000**: nine weapon indices, target 8; core inventory target 7. The comparison sites are **0x1803614cc** and **0x180361609**.
- `bigbot.checkforach` **0x180af3690**: six friendly icon entries.
- `crewchecker.checkcharacters` **0x18070c600** and `npc_generic.calcsaymund` **0x180f79af0**: exact NPC requirements.
- `status.LevelUp` **0x180365810**, `status.SaveTheGame` **0x18036ca80**: the offset used for Experienced is serialized as `socketsmax`.
- Ending coroutine **0x1805fdfb0**: Original difficulty, zero-death and 10,800-second checks. `difficultymenu.GoNormal` **0x18071af30** sets difficulty 1; `GoEasy` **0x18071ade0** sets 0.
- `RoslockWorker.SpawnLoot` **0x18057f920**: Frenzied Shell uses a fixed 3% roll with no Luck input. Green Godseed does not improve it.

Navigation landmarks are cross-checked with player reports where needed. The [developer's 1.2.12 announcement](https://steamcommunity.com/app/347800/discussions/0/3881596897254872885/) points toward the new region near Junkpit, and the [official update post](https://store.steampowered.com/news/posts/?enddate=1695927909&feed=steam_community_announcements) identifies Xorogon, the axe and Leaf's Heartbreaker. The [firsthand Toler-Under-Foot route report](https://gamefaqs.gamespot.com/boards/378658-ghost-song/80220407?page=6) matches the extracted Huttle Drop doorway chain. The [community achievement guide](https://steamcommunity.com/sharedfiles/filedetails/?id=2885185455) provides additional landmark context; its collection counts and assumptions are not used in place of native checks.

Pasha's Lupoto travel gate is **`otherdata[71]`**, while her Familiar completion flag is **`miscworldstate[64]`**. The crashed-pod encounter normally requires day 4 (three returned parts) and the preceding camp conversation. Guidance reports saved prerequisites; room-change timers and further game state can still affect spawning. It does not repair quests.

The progress catalog targets this inspected build. A different release, unusual edited state or engine quirks can make the interpretation incomplete. No full game playthrough was automated. Binary Ninja's headless loader was unavailable due to licensing; asset extraction and Capstone inspection supplied the native evidence.

## Save integrity and tests

The MS-NRBF codec and load-time safety checks are unchanged. Every opened file must survive a byte-identical decode/encode round trip. Keys, graph structure, list sizes and untouched primitive bytes remain intact. Numeric edits are type/range checked. Every edited export is parsed again, compared with the intended leaf values, and checked for the exact expected number of changes. Structural keys and sizes remain protected. Both file selection and drag/drop protect pending edits, including edits after a previous download.

The browser tests use synthetic files for the default read-only view, report download, all 42 goals, 39/40 vs 8/9 vs 7/8 targets, missing-core identity, shop stock semantics, partial/missing fields, logical list size, cross-slot shared unlocks, runtime-only goals, NPC requirements, run limits, New Game Plus and safe editing/reverting. A local validation against the supplied save also verifies an identical backup, a one-byte Frenzied Shell edit, desktop/mobile views and no browser script errors. Personal save data and game assets are not committed.
