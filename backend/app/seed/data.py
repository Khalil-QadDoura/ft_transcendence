"""Deterministic demo dataset definitions for BE-32 (make seed / make reset-demo)."""

from dataclasses import dataclass
from decimal import Decimal

# Demo-only password documented in README.md ("Demo accounts"), never used in production.
DEMO_PASSWORD = "WozuDemo2026!"

# Deterministic object key prefixes so seeded media assets are easy to recognise and clean up.
SEED_KEY_PREFIX = "seed-demo"


@dataclass(frozen=True)
class EmployerSpec:
    email: str
    first_name: str
    last_name: str
    position: str
    bio: str
    avatar_bg: tuple[int, int, int]
    company_name: str
    company_description: str
    country: str
    country_code: str
    city: str
    district: str
    logo_bg: tuple[int, int, int]
    logo_monogram: str


@dataclass(frozen=True)
class CandidateSpec:
    email: str
    first_name: str
    last_name: str
    position: str
    bio: str
    avatar_bg: tuple[int, int, int]
    video_asset: str
    video_rating: str
    include_rejected_video: bool = False


@dataclass(frozen=True)
class JobSpec:
    employer_email: str
    title: str
    description: str
    status: str
    latitude: float
    longitude: float
    location: str
    salary_amount: Decimal
    salary_type: str
    salary_currency: str
    schedule: str
    urgency: str


@dataclass(frozen=True)
class ApplicationSpec:
    applicant_email: str
    job_title: str
    status: str
    cover_note: str
    status_note: str | None = None


@dataclass(frozen=True)
class FriendshipSpec:
    requester_email: str
    addressee_email: str
    status: str


@dataclass(frozen=True)
class MessageSpec:
    sender_email: str
    content: str
    key_suffix: str


@dataclass(frozen=True)
class ConversationSpec:
    key: str
    title: str | None
    participant_emails: tuple[str, str]
    messages: tuple[MessageSpec, ...]
    # Email of participant who has NOT read the final message (creates realistic unread badge).
    unread_for_email: str | None = None
    linked_job_title: str | None = None
    linked_applicant_email: str | None = None


DEMO_EMPLOYERS: tuple[EmployerSpec, ...] = (
    EmployerSpec(
        email="employer1@wozu.demo",
        first_name="Layla",
        last_name="Al-Mansoori",
        position="Head of Talent",
        bio="Leading engineering and AI product hiring across Abu Dhabi.",
        avatar_bg=(30, 58, 138),
        company_name="Falcon Robotics AE",
        company_description=(
            "Autonomous warehouse logistics and industrial inspection robotics headquartered on "
            "Al Maryah Island, Abu Dhabi."
        ),
        country="United Arab Emirates",
        country_code="AE",
        city="Abu Dhabi",
        district="Al Maryah Island",
        logo_bg=(15, 23, 42),
        logo_monogram="FR",
    ),
    EmployerSpec(
        email="employer2@wozu.demo",
        first_name="Rashad",
        last_name="Mammadov",
        position="Engineering Director",
        bio="Building cloud-native fintech and maritime telemetry teams in Baku.",
        avatar_bg=(6, 95, 70),
        company_name="Caspian Cloud Systems",
        company_description=(
            "Distributed telemetry, real-time payments infrastructure, and developer tools "
            "engineered in Baku White City."
        ),
        country="Azerbaijan",
        country_code="AZ",
        city="Baku",
        district="White City",
        logo_bg=(6, 78, 59),
        logo_monogram="CC",
    ),
)


DEMO_CANDIDATES: tuple[CandidateSpec, ...] = (
    CandidateSpec(
        email="candidate1@wozu.demo",
        first_name="Amina",
        last_name="Karimova",
        position="Full-Stack Engineer",
        bio="Python, FastAPI, PostgreSQL and React developer focused on real-time web systems.",
        avatar_bg=(79, 70, 229),
        video_asset="demo_intro_1.mp4",
        video_rating="A",
        include_rejected_video=True,
    ),
    CandidateSpec(
        email="candidate2@wozu.demo",
        first_name="Omar",
        last_name="Al-Nuaimi",
        position="DevOps & SRE Specialist",
        bio="Docker, Nginx, Prometheus, Vault and high-availability database operations.",
        avatar_bg=(13, 148, 136),
        video_asset="demo_intro_2.mp4",
        video_rating="A",
    ),
    CandidateSpec(
        email="candidate3@wozu.demo",
        first_name="Sara",
        last_name="Hasanova",
        position="Product Designer",
        bio="Bilingual RTL/LTR interface design systems, accessibility and user research.",
        avatar_bg=(180, 83, 9),
        video_asset="demo_intro_3.mp4",
        video_rating="B",
    ),
    CandidateSpec(
        email="candidate4@wozu.demo",
        first_name="Tariq",
        last_name="Haddad",
        position="Junior Backend Developer",
        bio="Recent 42 graduate building REST APIs, Redis queues and SQL migrations.",
        avatar_bg=(190, 24, 93),
        video_asset="demo_intro_1.mp4",
        video_rating="B",
    ),
)


# 20 open jobs (10 in Abu Dhabi, 10 in Baku) + 2 draft jobs for employer "My Jobs" management.
DEMO_JOBS: tuple[JobSpec, ...] = (
    # --- Abu Dhabi (10 open) ---
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Senior Backend Engineer (Python / FastAPI)",
        description=(
            "Design resilient async microservices with FastAPI, PostgreSQL/PostGIS and Redis "
            "pub/sub for fleet orchestration across Abu Dhabi facilities."
        ),
        status="open",
        latitude=24.5002,
        longitude=54.3896,
        location="Al Maryah Island, Abu Dhabi",
        salary_amount=Decimal("24000.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="full_time",
        urgency="hot",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Frontend TypeScript & React Developer",
        description=(
            "Build live robotics telemetry dashboards, interactive map views and accessible "
            "operator consoles in React 19 and Tailwind CSS."
        ),
        status="open",
        latitude=24.4926,
        longitude=54.4071,
        location="Al Reem Island, Abu Dhabi",
        salary_amount=Decimal("19500.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="full_time",
        urgency="urgent",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Site Reliability & Security Engineer",
        description=(
            "Operate containerized workloads with ModSecurity WAF, Vault secrets rotation, "
            "Prometheus alerting and automated disaster-recovery backups."
        ),
        status="open",
        latitude=24.4292,
        longitude=54.6149,
        location="Masdar City, Abu Dhabi",
        salary_amount=Decimal("26000.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="full_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Computer Vision Intern",
        description=(
            "Assist the perception team with camera calibration, frame labeling pipelines and "
            "embedded model benchmarking during a 12-week paid internship."
        ),
        status="open",
        latitude=24.5446,
        longitude=54.4342,
        location="Saadiyat Island, Abu Dhabi",
        salary_amount=Decimal("6500.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="internship",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Robotics Field Operations Specialist",
        description=(
            "Commission autonomous pallet movers on client sites in Khalifa Port and Musaffah, "
            "diagnose Wi-Fi coverage issues and train site technicians."
        ),
        status="open",
        latitude=24.3558,
        longitude=54.5046,
        location="Musaffah Industrial, Abu Dhabi",
        salary_amount=Decimal("850.00"),
        salary_type="daily",
        salary_currency="AED",
        schedule="part_time",
        urgency="urgent",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Product Designer (RTL & Mobile Web)",
        description=(
            "Craft bilingual Arabic/English interfaces with seamless RTL mirroring, clear "
            "application workflows and high-contrast map interactions."
        ),
        status="open",
        latitude=24.4764,
        longitude=54.3498,
        location="Corniche Road, Abu Dhabi",
        salary_amount=Decimal("18000.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="full_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="QA Automation Engineer (Playwright)",
        description=(
            "Write deterministic browser integration suites covering WebSocket chat, OAuth "
            "login and responsive accessibility checks across Chromium and Firefox."
        ),
        status="open",
        latitude=24.4888,
        longitude=54.6052,
        location="Yas Island, Abu Dhabi",
        salary_amount=Decimal("17000.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="full_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Embedded Linux Systems Consultant",
        description=(
            "Review real-time kernel scheduling and container startup latency on ARM64 edge "
            "gateways for cold-chain sensors."
        ),
        status="open",
        latitude=24.4208,
        longitude=54.5764,
        location="Khalifa City, Abu Dhabi",
        salary_amount=Decimal("220.00"),
        salary_type="hourly",
        salary_currency="AED",
        schedule="part_time",
        urgency="hot",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Technical Recruiter (42 / Engineering)",
        description=(
            "Review candidate intro videos, coordinate technical challenges and guide "
            "applicants from screening through onboarding."
        ),
        status="open",
        latitude=24.4628,
        longitude=54.3712,
        location="Al Nahyan, Abu Dhabi",
        salary_amount=Decimal("15500.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="full_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Data & PostGIS Spatial Analyst",
        description=(
            "Optimize warehouse routing heatmaps, geospatial indexing and weekly fleet "
            "utilization reporting across UAE logistics hubs."
        ),
        status="open",
        latitude=24.4426,
        longitude=54.4472,
        location="Al Bateen, Abu Dhabi",
        salary_amount=Decimal("4200.00"),
        salary_type="weekly",
        salary_currency="AED",
        schedule="part_time",
        urgency="normal",
    ),
    # --- Baku (10 open) ---
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Platform SRE (Containers & Observability)",
        description=(
            "Own multi-service observability with Prometheus, Grafana, cAdvisor and Redis "
            "failover drills for high-throughput payment gateways in Baku."
        ),
        status="open",
        latitude=40.3797,
        longitude=49.8926,
        location="White City, Baku",
        salary_amount=Decimal("4800.00"),
        salary_type="monthly",
        salary_currency="AZN",
        schedule="full_time",
        urgency="hot",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="PostgreSQL & Distributed Systems Engineer",
        description=(
            "Architect zero-downtime Alembic schema migrations, transactional event logs and "
            "point-in-time recovery pipelines."
        ),
        status="open",
        latitude=40.3738,
        longitude=49.8584,
        location="Port Baku, Baku",
        salary_amount=Decimal("5200.00"),
        salary_type="monthly",
        salary_currency="AZN",
        schedule="full_time",
        urgency="urgent",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Full-Stack Python & React Developer",
        description=(
            "Ship customer-facing merchant analytics, WebSocket status feeds and clean REST "
            "endpoints tested end-to-end."
        ),
        status="open",
        latitude=40.3771,
        longitude=49.8407,
        location="Nizami Street, Baku",
        salary_amount=Decimal("4100.00"),
        salary_type="monthly",
        salary_currency="AZN",
        schedule="full_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="UX / UI Product Designer",
        description=(
            "Lead typography, multi-language layouts (AZ/EN/RU/TR/AR) and design system "
            "accessibility improvements across Caspian Cloud web apps."
        ),
        status="open",
        latitude=40.3661,
        longitude=49.8352,
        location="Icherisheher, Baku",
        salary_amount=Decimal("3600.00"),
        salary_type="monthly",
        salary_currency="AZN",
        schedule="full_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Backend Intern (42 Baku Track)",
        description=(
            "Work alongside senior engineers writing FastAPI endpoints, Celery background "
            "workers and automated pytest integration suites."
        ),
        status="open",
        latitude=40.4027,
        longitude=49.8655,
        location="Narimanov District, Baku",
        salary_amount=Decimal("1200.00"),
        salary_type="monthly",
        salary_currency="AZN",
        schedule="internship",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Application Security Reviewer",
        description=(
            "Conduct route authorization audits, OWASP ModSecurity CRS tuning and automated "
            "secret scanning across deployment branches."
        ),
        status="open",
        latitude=40.3886,
        longitude=49.8421,
        location="28 May, Baku",
        salary_amount=Decimal("3200.00"),
        salary_type="monthly",
        salary_currency="USD",
        schedule="full_time",
        urgency="hot",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Maritime Telemetry Support Engineer",
        description=(
            "Monitor real-time vessel data streams, investigate intermittent WebSocket drops "
            "and assist port operators on shift rotations."
        ),
        status="open",
        latitude=40.3418,
        longitude=49.8312,
        location="Bayil, Sabail, Baku",
        salary_amount=Decimal("180.00"),
        salary_type="daily",
        salary_currency="AZN",
        schedule="part_time",
        urgency="urgent",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Frontend Accessibility & i18n Specialist",
        description=(
            "Audit WCAG contrast, keyboard navigation and zero-hardcoded-string localization "
            "across five active user languages."
        ),
        status="open",
        latitude=40.3829,
        longitude=49.8118,
        location="Yasamal, Baku",
        salary_amount=Decimal("750.00"),
        salary_type="weekly",
        salary_currency="AZN",
        schedule="part_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Media Pipeline & FFmpeg Engineer",
        description=(
            "Optimize video transcoding, frame extraction and presigned MinIO object uploads "
            "for high-volume candidate video pitches."
        ),
        status="open",
        latitude=40.3915,
        longitude=49.8784,
        location="Khatai District, Baku",
        salary_amount=Decimal("45.00"),
        salary_type="hourly",
        salary_currency="USD",
        schedule="part_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Technical Documentation & API Writer",
        description=(
            "Maintain OpenAPI schema guides, operational disaster-recovery runbooks and "
            "developer onboarding playbooks."
        ),
        status="open",
        latitude=40.3872,
        longitude=49.8531,
        location="Ganjlik, Baku",
        salary_amount=Decimal("2800.00"),
        salary_type="monthly",
        salary_currency="AZN",
        schedule="full_time",
        urgency="normal",
    ),
    # --- Draft jobs (hidden from public search, visible in employer "My Jobs") ---
    JobSpec(
        employer_email="employer1@wozu.demo",
        title="Fleet Simulation Engineer (Draft)",
        description="Upcoming Q1 opening for Gazebo and discrete-event robotics simulation.",
        status="draft",
        latitude=24.5002,
        longitude=54.3896,
        location="Al Maryah Island, Abu Dhabi",
        salary_amount=Decimal("22000.00"),
        salary_type="monthly",
        salary_currency="AED",
        schedule="full_time",
        urgency="normal",
    ),
    JobSpec(
        employer_email="employer2@wozu.demo",
        title="Staff Rust Network Engineer (Draft)",
        description="Draft specification for low-latency gateway proxy services in Baku.",
        status="draft",
        latitude=40.3797,
        longitude=49.8926,
        location="White City, Baku",
        salary_amount=Decimal("5800.00"),
        salary_type="monthly",
        salary_currency="AZN",
        schedule="full_time",
        urgency="normal",
    ),
)


# Applications covering every active workflow status:
# submitted, viewed, shortlisted, contacted, hired, rejected.
DEMO_APPLICATIONS: tuple[ApplicationSpec, ...] = (
    ApplicationSpec(
        applicant_email="candidate1@wozu.demo",
        job_title="Senior Backend Engineer (Python / FastAPI)",
        status="contacted",
        cover_note=(
            "Built FastAPI, PostgreSQL/PostGIS and Redis pub/sub services with full test coverage."
        ),
        status_note="Great intro video — let us schedule a technical chat.",
    ),
    ApplicationSpec(
        applicant_email="candidate4@wozu.demo",
        job_title="Senior Backend Engineer (Python / FastAPI)",
        status="submitted",
        cover_note=(
            "42 graduate eager to contribute to backend Python APIs and database migrations."
        ),
    ),
    ApplicationSpec(
        applicant_email="candidate3@wozu.demo",
        job_title="Product Designer (RTL & Mobile Web)",
        status="shortlisted",
        cover_note=(
            "Designed RTL Arabic and multilingual job portals with accessible Tailwind components."
        ),
        status_note="Strong RTL portfolio; shortlisted for final review.",
    ),
    ApplicationSpec(
        applicant_email="candidate2@wozu.demo",
        job_title="Site Reliability & Security Engineer",
        status="viewed",
        cover_note=(
            "Experienced with Vault AppRole, ModSecurity CRS and Prometheus container alerting."
        ),
    ),
    ApplicationSpec(
        applicant_email="candidate2@wozu.demo",
        job_title="Platform SRE (Containers & Observability)",
        status="hired",
        cover_note=(
            "Set up Grafana dashboards, backup automation and Redis cluster monitoring "
            "in production."
        ),
        status_note="Offer accepted — welcome to Caspian Cloud Systems!",
    ),
    ApplicationSpec(
        applicant_email="candidate1@wozu.demo",
        job_title="Full-Stack Python & React Developer",
        status="submitted",
        cover_note="Interested in joining the Baku team as a full-stack Python & React engineer.",
    ),
    ApplicationSpec(
        applicant_email="candidate4@wozu.demo",
        job_title="PostgreSQL & Distributed Systems Engineer",
        status="rejected",
        cover_note=(
            "Would love to learn high-throughput distributed Postgres tuning with your team."
        ),
        status_note=(
            "Position requires 5+ years of database internals; try our Backend Intern role."
        ),
    ),
)


DEMO_FRIENDSHIPS: tuple[FriendshipSpec, ...] = (
    FriendshipSpec(
        requester_email="candidate1@wozu.demo",
        addressee_email="candidate2@wozu.demo",
        status="accepted",
    ),
    FriendshipSpec(
        requester_email="candidate1@wozu.demo",
        addressee_email="candidate3@wozu.demo",
        status="accepted",
    ),
    FriendshipSpec(
        requester_email="candidate3@wozu.demo",
        addressee_email="candidate2@wozu.demo",
        status="pending",
    ),
)


DEMO_CONVERSATIONS: tuple[ConversationSpec, ...] = (
    ConversationSpec(
        key="app-contacted-amina",
        title=None,
        participant_emails=("employer1@wozu.demo", "candidate1@wozu.demo"),
        linked_job_title="Senior Backend Engineer (Python / FastAPI)",
        linked_applicant_email="candidate1@wozu.demo",
        unread_for_email="candidate1@wozu.demo",
        messages=(
            MessageSpec(
                sender_email="employer1@wozu.demo",
                content=(
                    "Hi Amina! We watched your intro video for our Senior Backend Engineer role "
                    "on Al Maryah Island and would love to chat."
                ),
                key_suffix="m1",
            ),
            MessageSpec(
                sender_email="candidate1@wozu.demo",
                content=(
                    "Thanks Layla! I am very excited about Falcon Robotics and available this week."
                ),
                key_suffix="m2",
            ),
            MessageSpec(
                sender_email="employer1@wozu.demo",
                content=(
                    "Great — does Thursday at 14:00 GST work for a 30-minute architecture call?"
                ),
                key_suffix="m3",
            ),
        ),
    ),
    ConversationSpec(
        key="app-hired-omar",
        title=None,
        participant_emails=("employer2@wozu.demo", "candidate2@wozu.demo"),
        linked_job_title="Platform SRE (Containers & Observability)",
        linked_applicant_email="candidate2@wozu.demo",
        unread_for_email=None,
        messages=(
            MessageSpec(
                sender_email="employer2@wozu.demo",
                content="Welcome aboard Omar! Excited to have you leading our Baku SRE stack.",
                key_suffix="m1",
            ),
            MessageSpec(
                sender_email="candidate2@wozu.demo",
                content="Thank you Rashad — looking forward to day one in White City!",
                key_suffix="m2",
            ),
        ),
    ),
    ConversationSpec(
        key="friends-amina-sara",
        title=None,
        participant_emails=("candidate1@wozu.demo", "candidate3@wozu.demo"),
        unread_for_email="candidate1@wozu.demo",
        messages=(
            MessageSpec(
                sender_email="candidate1@wozu.demo",
                content="Hey Sara! Did you see the new RTL designer role in Abu Dhabi?",
                key_suffix="m1",
            ),
            MessageSpec(
                sender_email="candidate3@wozu.demo",
                content=(
                    "Yes! Just submitted my video pitch and got shortlisted. "
                    "Up for Turing Duel later?"
                ),
                key_suffix="m2",
            ),
        ),
    ),
)
