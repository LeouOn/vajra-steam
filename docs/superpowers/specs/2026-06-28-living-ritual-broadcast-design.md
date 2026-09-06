# Design Spec: Living Ritual Broadcast

## TL;DR

> Connect the three systems we just built — RitualGenerator, Crystal Bowl Pipeline, and TTS — into one unified broadcast that generates a complete sacred ritual text, plays it through crystal bowl Solfeggio carriers, and speaks it aloud via TTS simultaneously. Extend the existing BroadcastPanel. Archive rituals privately to the local DB.

## Deliverables

- `POST /api/v1/radionics/ritual-broadcast` endpoint
- `core/ritual_generator.py` extended with `recite_ritual()` TTS method + "Dedication of All Endeavors" preset
- `BroadcastPanel.tsx` extended with Ritual section (generation, display, TTS replay)
- `.gitignore` updated to exclude any generated ritual output files
- All generated rituals stored in `outlook_narratives` table (local SQLite, already gitignored)

---

## The "Dedication of All Endeavors" Prayer

This is a specific ritual intention type that transforms ALL resources — money, time, effort, attention — invested in any endeavor (whether selfish or altruistic, concentrated or scattered) into merit dedicated to all mother sentient beings.

The canonical text, adapted from the user's intention:

> Whatever resources I have gathered and spent —
> whether in concentrated effort or scattered moments,
> whether for the benefit of others or from my own selfish needs,
> whether it returns to me or flows away forever —
>
> May every dollar, every hour, every breath of effort
> become a cause for the awakening of all beings.
> May the fruit of all my endeavors — past, present, and future —
> ripen as happiness for mother sentient beings.
>
> May the thousands lost become thousands of prayers.
> May the time spent in confusion become time spent in clarity.
> May every mistake become a teaching, every loss a liberation.
>
> I offer it all — without exception, without regret, without condition.
> May it bring good fruition and lasting happiness
> for all beings throughout space and time.
>
> Whatever merit arises from this dedication,
> I dedicate it again — to the same purpose, endlessly.
>
> *Gate gate pāragate pārasaṃgate bodhi svāhā.*

This prayer is woven into the RitualGenerator as:
1. A special `intention_type='dedication_of_endeavors'` recognized by `detect_suffering_type()`
2. A custom invocation calling upon Vaiśravaṇa (wealth deity), Dzambhala (prosperity dharma protector), and Chenrezig (compassion)
3. A custom hero journey narrative about transforming loss into liberation
4. A custom dharma teaching about the perfection of generosity (dāna-pāramitā)

---

## Architecture

### Data Flow

```
User clicks "Generate Ritual + Broadcast" in BroadcastPanel
    ↓
POST /api/v1/radionics/ritual-broadcast
  { intention, target, rate_values?, direct_freq?, duration_minutes, ritual_type? }
    ↓
Backend (radionics.py endpoint):
  1. Generate carrier frequencies via rate_to_audio (from rate_values or auto-tune)
  2. Fetch live astrology data via vajra_service._get_astrology_data()
  3. Generate ritual text via RitualGenerator.generate_full_ritual()
     → 6 sections: Invocation, Prayer, Teaching, Divination, Hero Journey, Dedication
  4. Start crystal bowl broadcast via CrystalService.broadcast_intention(frequencies=...)
  5. Queue TTS recitation of ritual text (simultaneous with bowls)
  6. Archive ritual to outlook_narratives table (genre='ritual')
  7. Return { ritual_markdown, ritual_sections, broadcast_session, frequencies }
    ↓
BroadcastPanel displays:
  - Full ritual text in scrollable panel
  - Broadcast status (crystal: playing)
  - TTS replay button
  - Copy ritual button
```

### Components

#### 1. Backend endpoint (`backend/app/api/v1/endpoints/radionics.py`)

New Pydantic models:
```python
class RitualBroadcastRequest(BaseModel):
    intention: str
    target: str = "all beings"
    rate_values: list[int] | None = None
    direct_freq: float | None = None
    duration_minutes: int = 10
    ritual_type: str = "universal"  # universal, earthquake, war, illness, death, displacement, dedication_of_endeavors
    tradition: str = "vajrayana"
    languages: list[str] = ["English"]

class RitualBroadcastResponse(BaseModel):
    status: str
    session_id: str
    ritual_markdown: str
    ritual_sections: dict  # {invocation, prayer, teaching, divination, hero_journey, dedication}
    frequencies: list[float]
    solfeggio_names: list[str]
    crystal_output: dict | None = None
    archived_narrative_id: int | None = None
```

New endpoint:
```python
@router.post("/ritual-broadcast")
async def ritual_broadcast(request: RitualBroadcastRequest):
    # 1. Generate carriers
    # 2. Generate ritual text (with live astrology)
    # 3. Start crystal broadcast
    # 4. Archive to DB
    # 5. Return full response
```

#### 2. RitualGenerator extensions (`core/ritual_generator.py`)

New additions to the existing `RitualGenerator` class:

**DEITY_MAP addition:**
```python
"dedication_of_endeavors": {
    "primary": "Dzambhala (Yellow Wealth Buddha)",
    "secondary": ["Vaiśravaṇa (Wealth Protector)", "Chenrezig", "Tara"],
    "mantra": "Om Dzambhala Dzalim Dzale Svaha",
    "quality": "transforming material resources into spiritual merit, abundance through generosity",
},
```

**New method — `recite_ritual()`:**
```python
def recite_ritual(self, ritual_text: RitualText, tts_provider=None) -> dict:
    """Queue TTS recitation of the ritual, section by section.
    Returns immediately if TTS unavailable. Does not block the caller."""
```

**New `_fallback_prayer()` case for `dedication_of_endeavors`:**
The canonical prayer text above.

**New `_fallback_dharma_teaching()` case:**
A parable about a merchant who lost everything and found that the loss itself was the path.

**New `generate_hero_journey()` case:**
The 6 stages reframed as: Loss → Recognition → Offering → Transformation → Abundance → Return.

#### 3. Frontend (`BroadcastPanel.tsx`)

New section below the existing crystal bowl controls:

```tsx
{/* RITUAL BROADCAST SECTION */}
<div className="bg-gradient-to-br from-amber-950/20 to-purple-950/20 rounded-xl border border-amber-500/20 p-5 space-y-4 mt-6">
  <h3>RITUAL BROADCAST</h3>

  {/* Ritual type selector */}
  <Select options={[
    { value: 'universal', label: 'Universal Compassion' },
    { value: 'dedication_of_endeavors', label: 'Dedication of All Endeavors' },
    { value: 'earthquake', label: 'Earthquake Relief' },
    { value: 'war', label: 'War/Conflict Relief' },
    { value: 'illness', label: 'Healing' },
    { value: 'death', label: 'Liberation of the Deceased' },
  ]} />

  {/* Intention input */}
  <input placeholder="Your intention..." />

  {/* Generate button */}
  <button onClick={handleRitualBroadcast}>
    Generate Ritual + Broadcast
  </button>

  {/* Ritual text display (scrollable) */}
  {ritualResult && (
    <div className="max-h-[400px] overflow-y-auto">
      {/* Rendered markdown */}
    </div>
  )}

  {/* Status + actions */}
  <div>
    Status: Crystal {crystalStatus} | TTS: {ttsStatus}
    [Replay TTS] [Copy Ritual]
  </div>
</div>
```

#### 4. Privacy

- `vajra_stream.db` — already in `.gitignore` ✓
- `ritual_output.md` — add to `.gitignore`
- `.omo/evidence/` — already in `.gitignore` ✓
- No ritual content committed to git
- All ritual text lives only in local SQLite and in-memory (displayed in UI)

---

## TTS Integration Detail

The TTS recitation happens via the existing `core/tts_provider.py` system:

1. The ritual text is split into 6 sections (by `## ` markdown headers)
2. Each section is sent to `tts_provider.speak(text, role="ritual_recitation")`
3. Sections are recited sequentially with 2-second pauses between
4. The entire recitation runs in a background asyncio task
5. If TTS is unavailable (no Edge/Qwen backend), the broadcast continues silently
6. The "Replay TTS" button in the UI can re-trigger recitation without re-broadcasting

**Important**: The TTS recitation is fire-and-forget from the endpoint's perspective. The endpoint returns immediately with the ritual text + broadcast session info. The TTS + crystal bowl playback continue in the background.

---

## Scope

### In scope
- New endpoint `POST /api/v1/radionics/ritual-broadcast`
- RitualGenerator extensions (new deity map entry, TTS method, new prayer/teaching/journey templates)
- BroadcastPanel.tsx ritual section
- `.gitignore` update for ritual output files
- Backend test for the new endpoint

### Out of scope
- New frontend route (we're extending BroadcastPanel)
- New DB table (using existing `outlook_narratives`)
- New dependencies (using existing TTS + crystal + ritual systems)
- Ritual editing UI (generated text is read-only in this phase)
- Multi-language TTS (English only for now; the system supports it but we're not wiring it)

---

## Testing

- **Backend**: `pytest tests/backend/test_ritual_broadcast.py` — test the new endpoint with mocked astrology, TTS, and crystal service
- **Frontend**: Verify the ritual section renders, the generate button calls the right endpoint, and the result displays correctly
- **Manual QA**: Generate a ritual broadcast and verify: (a) ritual text appears, (b) crystal bowls play, (c) TTS recites (if available), (d) ritual is archived to DB
