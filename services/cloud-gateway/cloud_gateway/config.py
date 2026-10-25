"""Gateway configuration: every key declared once with its default, unit and the requirement it serves.

Proposal values from the specification are defaults here and never literals in code. A deployment's TOML file is
merged over the packaged `defaults.toml`. Provider slots map to adapters and concrete model ids in config only, so
swapping the primary and fallback providers is a config change (MDL-26). Keys are never configuration values: a
provider names the secret it needs and the secret source supplies it (SEC-20)."""

from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cloud_gateway.operations import OperationsPolicy

DEFAULTS = Path(__file__).with_name("defaults.toml")
Environment = Literal["dev", "staging", "pilot", "production"]
AdapterKind = Literal["gemini", "vertex", "openai_compat", "nebius"]
Effort = Literal["none", "low", "medium", "high"]


def key(default: Any, *, serves: str, unit: str | None = None, ge: float | None = None, le: float | None = None) -> Any:
    """A declared key: its default, unit and the requirement it serves."""
    return Field(default, ge=ge, le=le, json_schema_extra={"serves": serves, "unit": unit})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Thinking(_Strict):
    """How a model's reasoning effort is set: a named level or a token budget, per OpenAI-style effort."""

    kind: Literal["level", "budget"]
    none: str | int | None = None
    low: str | int | None = None
    medium: str | int | None = None
    high: str | int | None = None

    def value(self, effort: Effort) -> str | int | None:
        return {"none": self.none, "low": self.low, "medium": self.medium, "high": self.high}[effort]


class AskSearch(_Strict):
    """The search endpoint Ask anything reads (STU-20): Programmable Search style JSON. The deployment restricts it to
    the safety lead's allow-list as well; the gateway filters every result again."""

    url: str = Field(pattern=r"^https://")
    secret: str  # the API key's name in the secret source, never the key itself (SEC-20)


class TavilySettings(_Strict):
    """Prepaid search credits have their own persistent cap; they are not inference dollars."""

    enabled: bool = False
    daily_credits: int = Field(default=50, ge=1, le=1000)
    total_credits: int = Field(default=500, ge=1, le=10000)
    expires_at: AwareDatetime | None = None


class NvidiaPodcastSpeech(_Strict):
    """NVIDIA's free API-catalog prototype endpoint only; no GPU rental or paid speech billing path."""

    enabled: bool = False
    access: Literal["free_prototyping"] = "free_prototyping"
    daily_characters: int = Field(default=20000, ge=1, le=100000)
    total_characters: int = Field(default=100000, ge=1, le=1000000)
    daily_requests: int = Field(default=100, ge=1, le=500)
    total_requests: int = Field(default=500, ge=1, le=2000)
    expires_at: AwareDatetime | None = None


class ModelSpec(_Strict):
    id: str
    thinking: Thinking | None = None


class ProviderSpec(_Strict):
    adapter: AdapterKind
    base_url: str
    secret: str  # the secret's name in the secret source, never the key itself (SEC-20)
    timeout_s: float = key(60.0, serves="ARC-12", unit="s", ge=1)
    connect_timeout_s: float = key(5.0, serves="ARC-06", unit="s", ge=0.1)
    # The request field an OpenAI-compatible provider reads the session pseudonym from, if any (PRV-25).
    pseudonym_field: str | None = None
    models: dict[str, ModelSpec]  # model alias (fast-model, strong-model, small-model) -> concrete model


class Price(_Strict):
    """USD per million tokens (MDL-29, BIZ-08)."""

    input: float = Field(ge=0)
    cached_input: float = Field(ge=0)
    output: float = Field(ge=0)


class GoogleVoice(_Strict):
    """Google's speech services for cloud voice (D124). Ids, locales, voices and prices were checked against Google's
    documentation on 2026-10-21 (defaults.toml records the sources) and are proposals until the pilot confirms them.
    Speech-to-Text and Text-to-Speech take the attached service identity (no API key path is documented); Live takes
    the Gemini API key named by `live_secret`, or the attached identity on Vertex AI."""

    project: str = Field(default="", pattern=r"^([a-z][a-z0-9-]{4,61}[a-z0-9])?$")
    # Speech-to-Text v2 streaming recognition. `chirp_3` streams in the `us` and `eu` locations only.
    stt_model: str = "chirp_3"
    stt_location: Literal["us", "eu"] = "eu"
    # The recognizer locale for each transcription language the bridge sends (VOC-25). Nigerian English is not
    # offered (2026-10-21); add "en-NG" first in the list when it is.
    stt_locales: dict[str, list[str]] = Field(default_factory=lambda: {"en": ["en-GB"]})
    # The recognizer's end of speech (speech_end_timeout, at least 500 ms); the session's silence holds on from it.
    stt_end_timeout_ms: int = key(500, serves="VOC-28", unit="ms", ge=500, le=60_000)
    stt_minute_usd: float = key(0.016, serves="BIZ-08", unit="USD/minute", ge=0)
    # Gemini Live (native audio): "gemini" is the Gemini API with `live_secret`; "vertex" is Vertex AI with the
    # attached identity in `live_location`.
    live_api: Literal["gemini", "vertex"] = "vertex"
    live_model: str = "gemini-live-2.5-flash-native-audio"
    live_voice: str = Field(default="Kore", pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    live_secret: str = "gemini_api_key"  # noqa: S105 -- the secret's name in the secret source, not a key
    live_location: str = Field(default="europe-west4", pattern=r"^[a-z]+-[a-z]+[0-9]$")
    # Cloud Text-to-Speech streaming synthesis, Chirp 3 HD (verbatim): the voice for each transcription language.
    tts_location: Literal["global", "us", "eu"] = "eu"
    tts_voices: dict[str, str] = Field(default_factory=lambda: {"en": "en-GB-Chirp3-HD-Kore"})
    tts_million_chars_usd: float = key(30.0, serves="BIZ-08", unit="USD/1M characters", ge=0)


class Quotas(_Strict):
    """Rate limits and spend caps. The subscription's own cap is its monthly allowance (`Tier`, BIZ-07, D33): school
    seats are set aside (D10, decided in D100), so nothing here is per school (MDL-29: no per-school budget). A
    licence is the one the subscription's entitlement names."""

    device_requests_per_minute: float = key(30.0, serves="SEC-20", unit="requests/min", ge=0)
    device_burst: float = key(10.0, serves="SEC-20", unit="requests", ge=1)
    licence_requests_per_minute: float = key(600.0, serves="SEC-20", unit="requests/min", ge=0)
    licence_burst: float = key(100.0, serves="SEC-20", unit="requests", ge=1)
    device_daily_spend_usd: float = key(2.0, serves="SEC-20", unit="USD", ge=0)
    # Optional deployment-wide Study ceiling, including unresolved provider reservations across all devices.
    study_daily_spend_usd: float | None = key(None, serves="SEC-20", unit="USD", ge=0)
    # Shared provider inference budget, persisted independently of metadata retention. Pending calls reserve their
    # full input/output bound before any provider send. Hosting charges are managed separately by the operator.
    deployment_daily_spend_usd: float | None = key(None, serves="SEC-20", unit="USD", ge=0)
    deployment_total_spend_usd: float | None = key(None, serves="SEC-20", unit="USD", ge=0)
    deployment_budget_expires_at: AwareDatetime | None = key(None, serves="SEC-20")
    deployment_max_output_tokens: int = key(8192, serves="SEC-20", unit="tokens", ge=1, le=65536)
    # Spend anomaly: today's spend over this multiple of the trailing daily mean (per device within its licence,
    # and per licence), once it is above the floor.
    anomaly_multiple: float = key(5.0, serves="SEC-20", ge=1)
    anomaly_trailing_days: int = key(7, serves="SEC-20", unit="days", ge=1)
    anomaly_min_usd: float = key(0.5, serves="SEC-20", unit="USD", ge=0)


class Tier(_Strict):
    """The online tier's usage allowance per student per month (BIZ-07, BIZ-08, BIZ-18; D33 and D121). The prices are
    TABLE BIZ-18a's (`Plans`); a term is `prepaid_term_months` months prepaid; the allowance resets each month of the
    paid period. Every paid plan and band gives one allowance with no premium quota (D121): LIST BIZ-08a formula 5,
    `price · (1 - gross margin) / p_blend`, at the lowest price a covered student's month brings in across the table,
    so every plan covers its cost, with `p_blend` the price per token of this gateway's price table at the usage mix of
    TABLE BIZ-08b (`cloud_gateway.tier`). If BIZ-08 shows a plan cannot cover its cost, the allowance changes before
    the price does: `allowance_usd_per_student_month` sets it directly. The checkout signs the token figure into the
    entitlement; the gateway holds each subscription to the same allowance in US dollars."""

    prepaid_term_months: int = key(3, serves="BIZ-07", unit="months", ge=1)  # D33
    gross_margin: float = key(0.6, serves="BIZ-08", unit="share", ge=0, le=0.99)  # proposal (BIZ-08 formula 4)
    # Unset: computed from TABLE BIZ-18a's lowest price per student month. Set: the allowance, whatever the prices.
    allowance_usd_per_student_month: float | None = key(None, serves="BIZ-18", unit="USD", ge=0)
    # TABLE BIZ-08b's usage mix for `p_blend` (proposals until pilot traces replace them): model calls per tutor turn
    # by the primary provider's model alias (Coach and the rule matcher on the fast model, Checker phrasing on the
    # small one), and tokens per call with the cached share of the input.
    calls_per_turn: dict[str, float] = key({"fast-model": 2.0, "small-model": 1.0}, serves="BIZ-08", unit="calls")
    input_tokens_per_call: float = key(3000.0, serves="BIZ-08", unit="tokens", ge=0)
    output_tokens_per_call: float = key(250.0, serves="BIZ-08", unit="tokens", ge=0)
    cache_hit_share: float = key(0.6, serves="BIZ-08", unit="share", ge=0, le=1)


Band = Literal["nigeria", "purchasing_power", "international"]
Billing = Literal["month", "term", "year"]
PlanId = Literal["jana_online", "jana_family"]
Feature = Literal["cloud_tier", "ask_anything", "study_area", "uploads", "recordings", "podcasts", "past_paper_import",
                  "online_voice", "exam_reminders"]  # fmt: skip
BANDS: tuple[Band, ...] = ("nigeria", "purchasing_power", "international")


class Offer(_Strict):
    """One price in a band's currency, in whole units of it (TABLE BIZ-18a)."""

    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: int = Field(ge=0)


class Limits(_Strict):
    """A plan's fair-use limits per student (TABLE BIZ-18a, the entitlement's `PlanLimits`); unset means none."""

    ask_anything_per_day: int | None = Field(None, ge=0)
    uploads_per_day: int | None = Field(None, ge=0)
    uploads_per_week: int | None = Field(None, ge=0)
    upload_max_pages: int | None = Field(None, ge=0)
    upload_max_mb: int | None = Field(None, ge=0)
    recording_hours_per_month: int | None = Field(None, ge=0)
    podcasts_per_day: int | None = Field(None, ge=0)
    voice_minutes_per_month: int | None = Field(None, ge=0)

    def granted(self) -> dict[str, int]:
        return {name: value for name, value in self.model_dump().items() if value is not None}


class Taste(_Strict):
    """Free's online taste (TABLE BIZ-18a): the whole offline product needs nothing (BIZ-02, D84)."""

    features: tuple[Feature, ...]
    limits: Limits


class Plan(_Strict):
    name: str
    priced_per: Literal["student", "subscription"]  # Jana Online per student; Jana Family per subscription
    max_students: int = Field(ge=1, le=20)
    features: tuple[Feature, ...] = Field(min_length=1)
    limits: Limits
    prices: dict[Band, dict[Billing, Offer]]


class Plans(_Strict):
    """TABLE BIZ-18a (D121): the plans, their prices by band and what each gives, in one table (`plans.toml`). The
    band comes from the billing country at checkout, never from the device (BIZ-18). `per_usd` converts a band's
    currency for the allowance only (proposal rates); prices are never converted for the payer."""

    nigeria_countries: frozenset[str]
    purchasing_power_countries: frozenset[str]
    per_usd: dict[str, float]
    free: Taste
    paid: dict[PlanId, Plan]

    @model_validator(mode="after")
    def _consistent(self) -> Plans:
        if self.nigeria_countries & self.purchasing_power_countries:
            raise ValueError("a country is in two price bands (BIZ-18)")
        for country in self.nigeria_countries | self.purchasing_power_countries:
            if len(country) != 2 or not country.isupper():
                raise ValueError(f"{country!r} is not an ISO 3166 alpha-2 country code")
        for plan_id, plan in self.paid.items():
            for band in BANDS:
                if not plan.prices.get(band):
                    raise ValueError(f"{plan_id} has no price in the {band} band (TABLE BIZ-18a)")
            for offers in plan.prices.values():
                for offer in offers.values():
                    if self.per_usd.get(offer.currency, 0) <= 0:
                        raise ValueError(f"{offer.currency} has no rate to US dollars for the allowance")
        return self


PLANS = Path(__file__).with_name("plans.toml")


def packaged_plans() -> Plans:
    return Plans.model_validate(tomllib.loads(PLANS.read_text()))


class Objectives(_Strict):
    availability: float = key(0.995, serves="OBS-22", ge=0, le=1)  # proposal: monthly
    availability_window_days: int = key(30, serves="OBS-22", unit="days", ge=1)
    # Engineering assumption: the specification sets a latency objective without a number yet.
    latency_p95_ms: int = key(20000, serves="OBS-22", unit="ms", ge=1)
    status_window_s: int = key(300, serves="OBS-22", unit="s", ge=10)
    status_min_samples: int = key(5, serves="OBS-22", ge=1)
    degraded_failure_ratio: float = key(0.05, serves="OBS-22", ge=0, le=1)
    outage_failure_ratio: float = key(0.5, serves="OBS-22", ge=0, le=1)
    check_interval_s: int = key(60, serves="OBS-22", unit="s", ge=1)


class GatewayConfig(_Strict):
    environment: Environment = "production"
    # The host devices connect to; the token signature covers it so a signature is useless elsewhere (SEC-21).
    audience_host: str = "gateway.jana.invalid"
    storage_dir: Path = Path("/var/lib/jana-cloud-gateway")
    log_path: Path | None = None
    # Secret-manager mount: one file per secret, named after the secret (SEC-20).
    secrets_dir: Path | None = None
    keychain_service: str = "jana.cloud-gateway"
    # At most an hour each: the gateway contract's bound on `expires_in` (SEC-21, D39).
    access_token_ttl_s: int = key(900, serves="SEC-21", unit="s", ge=60, le=3600)  # proposal: 15 minutes
    challenge_ttl_s: int = key(60, serves="SEC-21", unit="s", ge=5, le=3600)
    # OBS-22's proposal. An allowance month can last 31 days, but the allowance is held by the month's own running
    # total (`GatewayStore.allowance_spend`, kept until its month is over), never by summing request rows, so this
    # window need not cover a month (D33).
    metadata_retention_days: int = key(30, serves="OBS-22", unit="days", ge=1)  # proposal
    max_request_bytes: int = key(8_000_000, serves="MDL-23", unit="bytes", ge=1024)
    # The unauthenticated routes (registration, challenge, token) take small bodies only (SEC-21).
    max_auth_request_bytes: int = key(16_384, serves="SEC-21", unit="bytes", ge=1024)
    # Registration needs the subscription entitlement the checkout signed (BIZ-07, D70, SEC-21): the licensing
    # service's licence intermediates that sign entitlements, by key id (base64 raw Ed25519 public keys; public
    # values, not secrets). When `licences` is not empty, the entitlement's licence must also be on it. Registration
    # without an entitlement (a bare licence id) is open only in a developer environment.
    entitlement_keys: dict[str, str] = Field(default_factory=dict)
    licences: frozenset[str] = frozenset()
    open_registration: bool = False
    # Devices each covered student of a subscription may hold live credentials for at once (so a Jana Family
    # subscription of four students may hold four times as many); the licence portal frees a slot by revoking.
    devices_per_subscription: int = key(2, serves="SEC-21", unit="devices", ge=1)
    slots: dict[str, str]  # provider slot (primary, fallback) -> provider name
    providers: dict[str, ProviderSpec]
    prices: dict[str, Price] = Field(default_factory=dict)  # concrete model id -> price
    quotas: Quotas = Field(default_factory=Quotas)
    tier: Tier = Field(default_factory=Tier)
    plans: Plans = Field(default_factory=packaged_plans)
    study_memory_bytes: int = key(256 * 1024 * 1024, serves="STU-17", unit="bytes", ge=104857600)
    study_source_max_mb: int = key(100, serves="STU-02", unit="MiB", ge=1, le=100)
    study_source_max_pages: int = key(300, serves="STU-02", unit="pages", ge=1, le=300)
    # Engineering proposal for gateway extraction compute; generation is metered separately by real token usage.
    study_extract_page_usd: float = key(0.0001, serves="STU-12", unit="USD/page", ge=0)
    study_extract_chars_per_page: int = key(4000, serves="STU-12", unit="characters/page", ge=1000, le=10000)
    study_recording_max_minutes: int = key(120, serves="STU-02", unit="minutes", ge=1, le=120)
    study_extract_minute_usd: float = key(0.0001, serves="STU-12", unit="USD/minute", ge=0)
    # The Study candidate is selected independently from the tutor's strong model.
    study_model: str = Field(default="primary/fast-model", pattern=r"^[a-z][a-z0-9_-]*/[a-z][a-z0-9_-]*$")
    # Trusted deployment command, including its OS sandbox wrapper. Never supplied by a device request.
    study_worker_command: tuple[str, ...] = ()
    # Cloud voice (VOC-28, D124): our hosted Realtime endpoint. Speech to text, the Live voice and the verbatim voice
    # are Google's (`voice_google`); the tutor's words come from the device's own engine through the connection, never
    # from a model here. Audio and transcripts stay in memory for the length of one utterance or one spoken reply.
    voice_enabled: bool = False
    # The voice service's own host name, accepted as a token audience beside `audience_host` (SEC-21).
    voice_audience_host: str | None = None
    voice_google: GoogleVoice = Field(default_factory=lambda: GoogleVoice())
    voice_max_utterance_s: float = key(30.0, serves="VOC-28", unit="s", ge=1, le=120)
    voice_max_session_s: float = key(3600.0, serves="VOC-28", unit="s", ge=60)
    # Prewarm (D124): `session.created`, which opens the device's microphone, waits this long for the recognition
    # stream and the Live session to open; audio sent before they are open is held, up to `voice_first_words_ms`.
    voice_prewarm_s: float = key(2.0, serves="VOC-28", unit="s", ge=0, le=10)
    voice_connect_timeout_s: float = key(5.0, serves="VOC-28", unit="s", ge=0.5, le=30)
    voice_first_words_ms: int = key(10_000, serves="VOC-28", unit="ms", ge=1000, le=30_000)
    # Sound kept while the upstream sessions are released for idleness, sent first when a sound reopens them.
    voice_preroll_ms: int = key(500, serves="VOC-28", unit="ms", ge=100, le=2000)
    # A recognition stream is replaced at a quiet moment after this long (the provider's limit is 5 minutes).
    voice_stt_rotate_s: float = key(240.0, serves="VOC-28", unit="s", ge=30, le=290)
    # After speech stops, how long the final transcript of the last words may take to arrive.
    voice_final_wait_ms: int = key(1500, serves="VOC-28", unit="ms", ge=100, le=10_000)
    # Adaptive idle timeout: factor x the longest quiet stretch seen before the student spoke, within these bounds;
    # suspended while a turn runs. On expiry the upstream sessions are released until the next sound.
    voice_idle_min_s: float = key(60.0, serves="VOC-28", unit="s", ge=1)
    voice_idle_max_s: float = key(300.0, serves="VOC-28", unit="s", ge=1)
    voice_idle_factor: float = key(2.0, serves="VOC-28", ge=1, le=10)
    voice_idle_tick_s: float = key(1.0, serves="VOC-28", unit="s", ge=0.01, le=10)
    # How long a sentence waits for a Live session still opening before the verbatim voice reads it instead.
    voice_live_wait_s: float = key(1.0, serves="VOC-28", unit="s", ge=0, le=10)
    # Sentences one Live session reads before a fresh one replaces it, keeping its context small.
    voice_live_max_sentences: int = key(40, serves="VOC-28", ge=1, le=1000)
    # The device has this long to start answering a forwarded chat-completions request (VOC-40 keeps it talking).
    voice_llm_timeout_s: float = key(60.0, serves="VOC-40", unit="s", ge=5)
    # Ask anything (STU-20, D117): the model that writes the cited answer and the search backend it reads from.
    ask_model: str = Field(default="primary/fast-model", pattern=r"^[a-z][a-z0-9_-]*/[a-z][a-z0-9_-]*$")
    ask_search: AskSearch | None = None
    tavily: TavilySettings = Field(default_factory=TavilySettings)
    podcast_speech: NvidiaPodcastSpeech = Field(default_factory=NvidiaPodcastSpeech)
    ask_search_results: int = key(6, serves="STU-20", unit="sources", ge=1, le=10)
    ask_max_tokens: int = key(4096, serves="STU-20", unit="tokens", ge=512, le=16384)
    objectives: Objectives = Field(default_factory=Objectives)
    operations: OperationsPolicy | None = None

    @model_validator(mode="after")
    def _consistent(self) -> GatewayConfig:
        for slot, provider in self.slots.items():
            if provider not in self.providers:
                raise ValueError(f"slot {slot!r} names unknown provider {provider!r}")
            for model in self.providers[provider].models.values():
                if model.id not in self.prices:
                    raise ValueError(f"model {model.id!r} has no price: cost must be computable (MDL-29)")
        primary = self.providers.get(self.slots.get("primary", ""))
        for alias in self.tier.calls_per_turn:
            if primary is not None and alias not in primary.models:
                raise ValueError(f"the tier's usage mix names {alias!r}, not a model of the primary provider (BIZ-08)")
        if self.podcast_speech.enabled and self.podcast_speech.expires_at is None:
            raise ValueError("NVIDIA prototype Podcast speech requires an expiry")
        if self.open_registration and self.environment != "dev":
            raise ValueError("open registration is for the dev environment only")
        if self.tavily.enabled and (self.tavily.expires_at is None or self.ask_search is not None):
            raise ValueError("Tavily requires an expiry and must be the only configured search backend")
        if (
            self.quotas.deployment_daily_spend_usd is not None
            or self.quotas.deployment_total_spend_usd is not None
            or self.quotas.deployment_budget_expires_at is not None
        ):
            for amount in (self.quotas.deployment_daily_spend_usd, self.quotas.deployment_total_spend_usd):
                if amount is not None and not math.isfinite(amount):
                    raise ValueError("deployment spend limits must be finite")
            if self.voice_enabled or self.ask_search is not None:
                raise ValueError("the inference budget does not cover voice or search service charges; disable them")
        if self.voice_enabled and self.voice_google.live_model not in self.prices:
            raise ValueError("the Live voice model has no price: cost must be computable (MDL-29)")
        return self


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for name, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(name), dict) and name not in ("slots", "providers"):
            merged[name] = _merge(merged[name], value)
        else:
            merged[name] = value
    return merged


def load_config(path: Path | None = None, **overrides: Any) -> GatewayConfig:
    """The packaged defaults, the deployment file over them, then keyword overrides. `slots` and `providers` are
    replaced as a whole by a later layer, so a deployment never inherits a provider it did not name."""
    data = _merge({"plans": tomllib.loads(PLANS.read_text())}, tomllib.loads(DEFAULTS.read_text()))
    if path is not None:
        data = _merge(data, tomllib.loads(path.read_text()))
    return GatewayConfig.model_validate(_merge(data, overrides))
