import hashlib
import json
import os
import re
import secrets
import string
from datetime import datetime, timedelta
from io import BytesIO
from typing import Dict, List, Tuple, Optional
import pickle

import numpy as np
import pandas as pd
import streamlit as st
import warnings

# Keep the output clean
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, message="Could not infer format.*")

try:
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    PRESIDIO_AVAILABLE = True
except Exception:
    PRESIDIO_AVAILABLE = False

try:
    import pyarrow.parquet as pq
    PYARROW_AVAILABLE = True
except Exception:
    PYARROW_AVAILABLE = False

try:
    import stripe
    STRIPE_AVAILABLE = True
except Exception:
    STRIPE_AVAILABLE = False


# =============================================================================
# Page configuration
# =============================================================================
st.set_page_config(
    page_title="Unified Data Catalog Platform",
    page_icon="Credence_logo.PNG",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Disable Streamlit magic so helper functions that return None are not rendered as visible "None" blocks.
try:
    st.set_option("runner.magicEnabled", False)
except Exception:
    pass

# =============================================================================
# Constants and reference taxonomy
# =============================================================================
APP_NAME = "Unified Data Catalog Platform"
APP_SUBTITLE = "Enabling Data Monetization Through Centralized Metadata Management and Governed Data Sharing Across Multi-Tenant Cloud Environments"

FABRIC_URL = "https://app.fabric.microsoft.com/"
PURVIEW_URL = "https://purview.microsoft.com/"
POWERBI_URL = "https://app.powerbi.com/"

# Microsoft Fabric Lakehouse reference used by the prototype catalog.
# The Streamlit portal stores and displays the metadata reference, while the physical demo files remain in Fabric/OneLake.
FABRIC_WORKSPACE_NAME = "TM Credence Data Monetization Platform"
FABRIC_LAKEHOUSE_NAME = "TM_Credence_Monetization_Lakehouse"
FABRIC_WORKSPACE_ID = "58cf53e5-705d-4338-8a73-c8eafd3fc5ab"
FABRIC_LAKEHOUSE_ID = "f2d341e1-ce91-4c43-a0f8-0d12fef6c912"
FABRIC_RELATIVE_FOLDER = "Files/raw/owner_demo"
FABRIC_PORTAL_LAKEHOUSE_URL = (
    f"https://app.fabric.microsoft.com/groups/{FABRIC_WORKSPACE_ID}/lakehouses/{FABRIC_LAKEHOUSE_ID}"
    "?experience=fabric-developer&selectedPath=Files%2Fraw%2Fowner_demo"
)
FABRIC_ONELAKE_FOLDER_URL = (
    f"https://onelake.dfs.fabric.microsoft.com/{FABRIC_WORKSPACE_ID}/{FABRIC_LAKEHOUSE_ID}/{FABRIC_RELATIVE_FOLDER}"
)
FABRIC_ABFSS_FOLDER_PATH = (
    f"abfss://{FABRIC_WORKSPACE_ID}@onelake.dfs.fabric.microsoft.com/{FABRIC_LAKEHOUSE_ID}/{FABRIC_RELATIVE_FOLDER}"
)


# Monetization model: every catalog purchase produces revenue for the data provider,
# while a small platform service commission is retained by the MSP operator.
MSP_COMMISSION_RATE = 0.05  # 5% platform commission for Credence/MSP

# Demo source files used across the report and Fabric Lakehouse evidence.
DEMO_DATASET_FILES = ["customer.csv", "billing.csv", "service.csv"]

# Tenant types represent organizations in the multi-tenant platform.
TENANT_TYPES = ["MSP", "Data Provider", "Data Consumer"]

# User roles are provisioned inside a tenant. These are inspired by Microsoft Purview catalog/governance roles and Microsoft Fabric workspace roles, but adapted to this MSP data monetization platform.
MSP_ROLES = [
    "MSP Administrator",
    "Governance Administrator",
    "Marketplace Administrator",
    "Catalog Administrator",
    "Platform Operator",
]

PROVIDER_ROLES = [
    "Provider Administrator",
    "Data Owner",
    "Data Steward",
    "Data Contributor",
]

CONSUMER_ROLES = [
    "Consumer Administrator",
    "Consumer User",
]

ROLES = MSP_ROLES + PROVIDER_ROLES + CONSUMER_ROLES

ROLE_GROUPS = {
    "MSP": MSP_ROLES,
    "Data Provider": PROVIDER_ROLES,
    "Data Consumer": CONSUMER_ROLES,
}

ROLE_DESCRIPTIONS = pd.DataFrame(
    [
        ["MSP", "MSP Administrator", "Highest platform role. Manages tenants, users, provider approval settings, policies, datasets, access requests and audit logs."],
        ["MSP", "Governance Administrator", "Reviews privacy scan results, sensitivity classification, compliance policies and high-risk dataset approval."],
        ["MSP", "Marketplace Administrator", "Manages paid/free catalog publication, consumer access requests, payment simulation and revenue monitoring."],
        ["MSP", "Catalog Administrator", "Curates catalog metadata, tags, glossary-like information, dataset publication readiness and catalog quality."],
        ["MSP", "Platform Operator", "Monitors governance alerts, policy findings, access anomalies, catalog compliance and platform audit activity."],
        ["Data Provider", "Provider Administrator", "Manages provider tenant users, registers datasets, configures pricing and oversees provider-side publication workflow."],
        ["Data Provider", "Data Owner", "Owns TM One datasets, submits publication requests, approves consumer requests and defines dataset access intent."],
        ["Data Provider", "Data Steward", "Maintains metadata quality, tags, descriptions, classifications and governance readiness for provider datasets."],
        ["Data Provider", "Data Contributor", "Registers datasets and triggers metadata/privacy/quality scans but cannot publish or approve access independently."],
        ["Data Consumer", "Consumer Administrator", "Manages consumer tenant usage, purchases or requests datasets and monitors tokens for the organization."],
        ["Data Consumer", "Consumer User", "Browses the published catalog, requests access and downloads authorized datasets for PSM research use."],
    ],
    columns=["Tenant Category", "Role", "Purpose"],
)

# Business sensitivity labels inspired by Microsoft Purview sensitivity label practice.
# Purview itself supports configurable sensitivity labels; this prototype uses a  five-level taxonomy.
CLASSIFICATION_LEVELS = [
    "Public",
    "Internal",
    "Confidential",
    "Restricted",
    "Highly Restricted",
]

CLASSIFICATION_GUIDE = pd.DataFrame(
    [
        ["Public", "Open data with no sensitive information", "Public catalog listing; standard purchase/access workflow"],
        ["Internal", "Business-useful internal data with low sensitivity", "Registered users only; basic audit logging"],
        ["Confidential", "Contains PII, commercial, financial, or business-sensitive attributes", "Approval required; masking recommended"],
        ["Restricted", "Contains strong identifiers, regulated data, government IDs, or high privacy risk", "Manual MSP/governance review; token expiry enforced"],
        ["Highly Restricted", "Contains multiple sensitive categories or severe compliance risk", "Strict approval, masking, limited access, high audit requirement"],
    ],
    columns=["Classification", "Meaning", "Recommended Control"],
)

PURVIEW_STYLE_CLASSIFICATIONS = [
    "Person Name",
    "Email Address",
    "Phone Number",
    "Malaysia NRIC",
    "Passport Number",
    "Credit Card Number",
    "Financial Information",
    "Health Information",
    "Government Identifier",
    "Address / Location",
    "Date / Time",
    "Biometric Information",
]

SOURCE_PLATFORMS = [
    "CSV File", "Excel File", "Parquet File", "JSON File",
    "Microsoft Fabric Lakehouse", "Azure Data Lake Storage", "Amazon S3", "SharePoint",
    "PostgreSQL", "Oracle", "MySQL", "Iceberg Table", "REST API", "GraphQL API",
]

REGISTRATION_METHODS = ["File Upload", "External Storage URL", "Database Connection", "API Endpoint"]
DATASET_FORMATS = ["CSV", "Excel", "Parquet", "JSON", "Delta", "Table", "API", "Unknown"]
DATASET_STATUSES = [
    "Draft",
    "Submitted",
    "Privacy Review",
    "MSP Review",
    "Approved",
    "Published",
    "Suspended",
    "Rejected"
]
PAYMENT_METHODS = [
    "Online Banking / FPX",
    "Credit / Debit Card",
    "Touch 'n Go eWallet",
    "GrabPay"
]
PAYMENT_MODES = ["Simulated Gateway", "Stripe Sandbox Checkout"]
STRIPE_DEFAULT_PAYMENT_METHOD_TYPES = ["card", "fpx", "grabpay"]
DEMO_MASKED_DATASET_FILES = {
    "customer.csv": "customer_masked.csv",
    "billing.csv": "billing_masked.csv",
    "service.csv": "service_masked.csv",
}
DEMO_AUTHORIZED_DATASET_FILES = {
    "service.csv": "authorized_service.csv",
}
PROCESSING_REPORT_FILES = {
    "processing_summary": "processing_summary_report.csv",
    "privacy_masking_policy": "privacy_and_masking_policy_report.csv",
    "dataset_quality_scores": "dataset_quality_scores.csv",
    "column_level_quality": "column_level_quality_report.csv",
}

# Processing output CSV files generated by the Fabric processing notebook.
# The four report files contain all datasets, so the catalog detail page filters
# each report by dataset_name = customer / billing / service based on the selected asset.
PROCESSING_OUTPUT_FILE_PATHS = {
    "customer_masked": "customer_masked.csv",
    "billing_masked": "billing_masked.csv",
    "service_masked": "service_masked.csv",
    "privacy_and_masking_policy_report": "privacy_and_masking_policy_report.csv",
    "processing_summary_report": "processing_summary_report.csv",
    "dataset_quality_scores": "dataset_quality_scores.csv",
    "column_level_quality_report": "column_level_quality_report.csv",
}
POLICY_TYPES = ["Access Policy", "Masking Policy", "Retention Policy", "Approval Policy", "Compliance Policy"]

DIRECT_IDENTIFIER_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "MY_PHONE_NUMBER", "MY_NRIC",
    "PASSPORT", "CREDIT_CARD", "IP_ADDRESS", "NRP",
]
QUASI_IDENTIFIER_ENTITIES = ["LOCATION", "DATE_TIME"]
FULL_MASK_COLUMNS = ["nric", "passport", "credit_card", "card_number", "bank_account", "account_number"]
PARTIAL_MASK_COLUMNS = ["full_name", "phone", "email", "address"]
PRESERVE_COLUMNS = [
    "customer_id", "service_id", "invoice_id",
    "customer_type", "company_name", "industry_sector",
    "state", "district", "postcode",
    "subscription_plan", "subscription_start_date", "subscription_end_date",
    "status", "payment_method", "billing_cycle",
    "preferred_language", "gender", "age", "income",
    "sme_flag", "kyc_status",
    "billing_period_start", "billing_period_end",
    "pricing_tier", "currency",
    "subtotal_amount", "discount_amount", "tax_amount", "total_amount",
    "service_category", "service_status", "region",
    "access_technology", "router_model", "device_os", "sla_tier",
    "service_start_date", "service_end_date",
    "bandwidth_mbps", "monthly_usage_gb",
    "avg_latency_ms", "jitter_ms", "monthly_outages"
]

SENSITIVE_KEYWORDS = {
    "PII": ["name", "email", "phone", "address", "nric", "passport", "dob", "birth", "postcode"],
    "Financial Data": ["income", "salary", "bank", "account", "credit", "card", "payment", "invoice", "tax", "amount", "revenue", "billing"],
    "Health Data": ["health", "medical", "diagnosis", "patient", "disease", "clinic", "hospital", "blood", "insurance"],
    "Government Data": ["nric", "passport", "ic", "government", "tax", "license", "permit", "nationality"],
    "Biometric Data": ["fingerprint", "face", "facial", "iris", "voice", "biometric"],
}

# =============================================================================
# Styling
# =============================================================================
st.markdown(
    """
    <style>
    .main-title {font-size:34px;font-weight:850;color:#111827;margin-bottom:4px;}
    .subtitle {font-size:15px;color:#4b5563;margin-bottom:18px;}
    .section-title {font-size:24px;font-weight:750;color:#111827;margin-top:12px;margin-bottom:10px;}
    .card {background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;margin-bottom:14px;box-shadow:0 2px 10px rgba(0,0,0,0.04);}
    .mini {font-size:13px;color:#6b7280;}
    .ok {color:#047857;font-weight:700;}
    .warn {color:#b45309;font-weight:700;}
    .bad {color:#b91c1c;font-weight:700;}
    .pill {display:inline-block;padding:4px 10px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:12px;font-weight:700;margin:2px 4px 2px 0;}
    .pill-green {background:#ecfdf5;color:#047857;}
    .pill-orange {background:#fff7ed;color:#c2410c;}
    .pill-red {background:#fef2f2;color:#b91c1c;}
    .pill-gray {background:#f3f4f6;color:#374151;}
    .flow-box {background:#f9fafb;border:1px dashed #d1d5db;border-radius:14px;padding:12px;margin:6px 0;font-size:14px;}
    .small-note {background:#f8fafc;border-left:4px solid #64748b;padding:10px 12px;border-radius:8px;color:#334155;font-size:14px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# Utility functions
# =============================================================================
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def generate_id(prefix: str) -> str:
    token = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"{prefix}-{token}"


def generate_access_token() -> str:
    parts = ["".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)) for _ in range(3)]
    return "DATA-" + "-".join(parts)


def add_log(actor: str, action: str, tenant: str = "System") -> None:
    row = pd.DataFrame([{"Time": now_str(), "Actor": actor, "Tenant": tenant, "Action": action}])
    if "audit_log" not in st.session_state or st.session_state.audit_log.empty:
        st.session_state.audit_log = row.copy()
    else:
        st.session_state.audit_log = pd.concat([st.session_state.audit_log, row], ignore_index=True)


def show_header(title: str, subtitle: str = "") -> None:
    st.markdown(f"<div class='main-title'>{title}</div>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<div class='subtitle'>{subtitle}</div>", unsafe_allow_html=True)


def show_card(title: str, body: str, status: Optional[str] = None) -> None:
    pill = ""
    if status:
        cls = "pill"
        if status in ["Approved", "Published", "Active", "Successful", "Low"]:
            cls += " pill-green"
        elif status in ["Rejected", "Expired", "High", "Highly Restricted", "Restricted"]:
            cls += " pill-red"
        elif status in ["Submitted", "Privacy Review", "MSP Review", "Medium", "Confidential"]:
            cls += " pill-orange"
        else:
            cls += " pill-gray"
        pill = f"<span class='{cls}'>{status}</span>"
    st.markdown(f"<div class='card'><b>{title}</b><br>{pill}<div class='mini' style='margin-top:8px'>{body}</div></div>", unsafe_allow_html=True)


def dataframe_download_button(df: pd.DataFrame, label: str, filename: str, key: Optional[str] = None) -> None:
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(label, data=csv, file_name=filename, mime="text/csv", key=key)

def find_project_file(filename: str) -> Optional[str]:
    candidate_paths = []
    try:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        candidate_paths.append(os.path.join(app_dir, filename))
    except Exception:
        pass
    candidate_paths.append(os.path.join(os.getcwd(), filename))
    candidate_paths.append(os.path.join("/mnt/data", filename))
    for path in candidate_paths:
        if os.path.exists(path):
            return path
    return None


def read_project_csv(filename: str) -> Optional[pd.DataFrame]:
    path = find_project_file(filename)
    if not path:
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        st.warning(f"Found {filename} but failed to read it: {e}")
        return None

def safe_read_upload(file) -> Tuple[Optional[pd.DataFrame], str, str]:
    if file is None:
        return None, "Unknown", "No file"
    name = file.name.lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(file), "CSV", "Loaded CSV file"
        if name.endswith(".xlsx") or name.endswith(".xls"):
            return pd.read_excel(file), "Excel", "Loaded Excel file"
        if name.endswith(".json"):
            return pd.read_json(file), "JSON", "Loaded JSON file"
        if name.endswith(".parquet"):
            return pd.read_parquet(file), "Parquet", "Loaded Parquet file"
        return None, "Unknown", "Unsupported file format"
    except Exception as e:
        return None, "Unknown", f"Failed to read file: {e}"


def ensure_review_tracking_columns() -> None:
    dataset_review_columns = {
        "rejection_reason": "",
        "rejected_by": "",
        "rejected_at": "",
        "suspension_reason": "",
        "suspended_by": "",
        "suspended_at": "",
    }
    access_request_review_columns = {
        "rejection_reason": "",
        "rejected_by": "",
        "rejected_at": "",
    }

    if "datasets" in st.session_state and isinstance(st.session_state.datasets, pd.DataFrame):
        for column_name, default_value in dataset_review_columns.items():
            if column_name not in st.session_state.datasets.columns:
                st.session_state.datasets[column_name] = default_value
            else:
                st.session_state.datasets[column_name] = st.session_state.datasets[column_name].fillna(default_value)

    if "access_requests" in st.session_state and isinstance(st.session_state.access_requests, pd.DataFrame):
        for column_name, default_value in access_request_review_columns.items():
            if column_name not in st.session_state.access_requests.columns:
                st.session_state.access_requests[column_name] = default_value
            else:
                st.session_state.access_requests[column_name] = st.session_state.access_requests[column_name].fillna(default_value)

    if "tokens" in st.session_state and isinstance(st.session_state.tokens, pd.DataFrame):
        if "consumer_tenant_id" not in st.session_state.tokens.columns:
            st.session_state.tokens["consumer_tenant_id"] = ""
        else:
            st.session_state.tokens["consumer_tenant_id"] = st.session_state.tokens["consumer_tenant_id"].fillna("")


DB_FILE = "prototype_db.pkl"

def save_prototype_state():
    keys_to_save = [
        "tenants", "users", "datasets", "metadata_store", "data_store",
        "quality_reports", "privacy_reports", "processing_outputs",
        "policies", "access_requests", "tokens", "governance_alerts",
        "audit_log", "payment_transactions", "current_user", "initialized",
        "newly_registered_dataset_id", "business_domains", "workspaces",
        "feedback", "sensitivity_catalog", "glossary_terms", "lineage_edges",
        "data_products", "usage_history"
    ]
    state_to_save = {}
    for k in keys_to_save:
        if k in st.session_state:
            state_to_save[k] = st.session_state[k]
    try:
        with open(DB_FILE, "wb") as f:
            pickle.dump(state_to_save, f)
    except Exception as e:
        st.warning(f"Failed to save state to disk: {e}")

def load_prototype_state() -> bool:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "rb") as f:
                saved_state = pickle.load(f)
                for k, v in saved_state.items():
                    st.session_state[k] = v
            return True
        except Exception:
            return False
    return False

# =============================================================================
# Presidio setup
# =============================================================================
@st.cache_resource(show_spinner=False)
def init_presidio():
    if not PRESIDIO_AVAILABLE:
        return None
    analyzer = AnalyzerEngine()
    nric_pattern = Pattern(name="Malaysia NRIC Pattern", regex=r"\b\d{6}-?\d{2}-?\d{4}\b", score=0.95)
    phone_pattern = Pattern(name="Malaysia Phone Pattern", regex=r"\b(\+?60|0)?1[0-9]{8,9}\b", score=0.85)
    passport_pattern = Pattern(name="Passport-like Pattern", regex=r"\b[A-Z][0-9]{7,8}\b", score=0.65)
    _ = analyzer.registry.add_recognizer(PatternRecognizer(supported_entity="MY_NRIC", patterns=[nric_pattern]))
    _ = analyzer.registry.add_recognizer(PatternRecognizer(supported_entity="MY_PHONE_NUMBER", patterns=[phone_pattern]))
    _ = analyzer.registry.add_recognizer(PatternRecognizer(supported_entity="PASSPORT", patterns=[passport_pattern]))
    return analyzer

analyzer = init_presidio()

# =============================================================================
# Data processing, metadata discovery and governance logic
# =============================================================================
def clean_dataset(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    duplicate_count = int(df.duplicated().sum())
    df = df.drop_duplicates()
    missing_values = ["", "nan", "none", "null", "na", "n/a", "-", "--"]
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()
    df = df.replace(missing_values, np.nan)

    for col in df.columns:
        if "date" in col or "time" in col or col.endswith("_start") or col.endswith("_end"):
            try:
                df[col] = pd.to_datetime(df[col])
            except Exception:
                pass
        elif df[col].dtype == "object":
            converted = pd.to_numeric(df[col], errors="coerce")
            ratio = converted.notna().mean() if len(df) else 0
            if ratio > 0.85:
                df[col] = converted

    if "postcode" in df.columns:
        df["postcode"] = df["postcode"].astype(str).str.replace(".0", "", regex=False).str.zfill(5)
        df["postcode"] = df["postcode"].replace("00nan", np.nan)

    if "phone" in df.columns:
        df["phone"] = df["phone"].astype(str).str.replace(" ", "", regex=False).str.replace("-", "", regex=False)
        df["phone"] = df["phone"].replace(["nan", "None", "null"], np.nan)

    return df, duplicate_count


def discover_metadata(df: Optional[pd.DataFrame], dataset_name: str, source_platform: str, fmt: str, source_uri: str = "") -> Dict:
    if df is None or df.empty:
        return {
            "Dataset Name": dataset_name,
            "Source Platform": source_platform,
            "Format": fmt,
            "Rows": 0,
            "Columns": 0,
            "Column Names": "",
            "Data Types": "",
            "Size Estimate KB": 0,
            "Last Updated": today_str(),
            "Source URI": source_uri,
        }
    memory_kb = round(df.memory_usage(deep=True).sum() / 1024, 2)
    return {
        "Dataset Name": dataset_name,
        "Source Platform": source_platform,
        "Format": fmt,
        "Rows": int(df.shape[0]),
        "Columns": int(df.shape[1]),
        "Column Names": ", ".join(df.columns.astype(str).tolist()),
        "Data Types": json.dumps({c: str(t) for c, t in df.dtypes.items()}),
        "Size Estimate KB": memory_kb,
        "Last Updated": today_str(),
        "Source URI": source_uri,
    }


def is_expected_missing(df: pd.DataFrame, col: str) -> pd.Series:
    if "customer_type" not in df.columns:
        return pd.Series(False, index=df.index)
    customer_type = df["customer_type"].astype(str).str.lower()
    expected = pd.Series(False, index=df.index)
    individual_expected_null_cols = ["company_name", "industry_sector", "sme_flag"]
    business_expected_null_cols = ["full_name", "gender", "age", "income", "nric"]
    if col in individual_expected_null_cols:
        expected = customer_type.eq("individual") & df[col].isnull()
    elif col in business_expected_null_cols:
        expected = customer_type.eq("business") & df[col].isnull()
    return expected


def generate_quality_report(df: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    report = []
    total_rows = len(df)
    for col in df.columns:
        raw_missing_count = int(df[col].isnull().sum())
        expected_missing_count = int(is_expected_missing(df, col).sum()) if col in df.columns else 0
        unexpected_missing_count = max(raw_missing_count - expected_missing_count, 0)
        unexpected_missing_percentage = unexpected_missing_count / total_rows * 100 if total_rows > 0 else 0
        completeness_score = 100 - unexpected_missing_percentage
        unique_count = int(df[col].nunique(dropna=True))
        if pd.api.types.is_numeric_dtype(df[col]):
            valid_count = int(pd.to_numeric(df[col], errors="coerce").notnull().sum())
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            valid_count = int(pd.to_datetime(df[col], errors="coerce").notnull().sum())
        else:
            valid_count = int(df[col].notnull().sum() + expected_missing_count)
        validity_score = valid_count / total_rows * 100 if total_rows > 0 else 0
        uniqueness_score = 100 if unique_count <= 30 and df[col].dtype == "object" else (unique_count / total_rows * 100 if total_rows else 0)
        overall = round(completeness_score * 0.45 + validity_score * 0.45 + uniqueness_score * 0.10, 2)
        status = "Excellent" if overall >= 90 else "Good" if overall >= 75 else "Moderate" if overall >= 60 else "Poor"
        _ = report.append({
            "dataset_name": dataset_name,
            "column_name": col,
            "data_type": str(df[col].dtype),
            "total_rows": total_rows,
            "raw_missing_count": raw_missing_count,
            "expected_missing_count": expected_missing_count,
            "unexpected_missing_count": unexpected_missing_count,
            "unique_count": unique_count,
            "completeness_score": round(completeness_score, 2),
            "validity_score": round(validity_score, 2),
            "uniqueness_score": round(uniqueness_score, 2),
            "overall_quality_score": overall,
            "quality_status": status,
        })
    return pd.DataFrame(report)


def analyze_column(series: pd.Series, col: str, sample_size: int = 50) -> Tuple[str, int, float, Dict[str, int]]:
    values = series.dropna().astype(str).head(sample_size)
    counts: Dict[str, int] = {}

    for value in values:
        if analyzer is not None:
            try:
                results = analyzer.analyze(text=value, language="en")
                for result in results:
                    counts[result.entity_type] = counts.get(result.entity_type, 0) + 1
            except Exception:
                pass

        # Regex fallback keeps the Streamlit app useful even when Presidio is unavailable.
        if re.search(r"\b\d{6}-?\d{2}-?\d{4}\b", value):
            counts["MY_NRIC"] = counts.get("MY_NRIC", 0) + 1
        if re.search(r"\b[A-Z][0-9]{7,8}\b", value):
            counts["PASSPORT"] = counts.get("PASSPORT", 0) + 1
        if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value):
            counts["EMAIL_ADDRESS"] = counts.get("EMAIL_ADDRESS", 0) + 1
        if re.search(r"\b(\+?60|0)?1[0-9]{8,9}\b", value.replace("-", "")):
            counts["MY_PHONE_NUMBER"] = counts.get("MY_PHONE_NUMBER", 0) + 1
        if re.search(r"\b(?:\d[ -]*?){13,16}\b", value):
            counts["CREDIT_CARD"] = counts.get("CREDIT_CARD", 0) + 1

    if len(counts) == 0 or len(values) == 0:
        return "None", 0, 0.0, {}

    dominant = max(counts, key=counts.get)
    dominant_count = int(counts[dominant])
    ratio = dominant_count / max(len(values), 1)
    return dominant, dominant_count, ratio, counts


def map_to_purview_style_classification(entity: str, col: str) -> str:
    col_lower = col.lower()
    if entity == "EMAIL_ADDRESS" or "email" in col_lower:
        return "Email Address"
    if entity in ["PHONE_NUMBER", "MY_PHONE_NUMBER"] or "phone" in col_lower:
        return "Phone Number"
    if entity == "MY_NRIC" or "nric" in col_lower or col_lower == "ic":
        return "Malaysia NRIC"
    if entity == "PASSPORT" or "passport" in col_lower:
        return "Passport Number"
    if entity == "CREDIT_CARD" or "credit_card" in col_lower:
        return "Credit Card Number"
    if entity == "PERSON" or "name" in col_lower:
        return "Person Name"
    if entity == "LOCATION" or "address" in col_lower or "state" in col_lower:
        return "Address / Location"
    if entity == "DATE_TIME" or "date" in col_lower:
        return "Date / Time"
    if entity == "Financial Data":
        return "Financial Information"
    if entity == "Health Data":
        return "Health Information"
    if entity == "Government Data":
        return "Government Identifier"
    if entity == "Biometric Data":
        return "Biometric Information"
    if entity == "PII":
        return "Person Name"
    return "None"


def determine_sensitivity(col: str, entity: str, ratio: float) -> Tuple[str, str, str]:
    col_lower = col.lower()

    if col_lower in PRESERVE_COLUMNS:
        return "Non-sensitive / Business-useful", "Preserve", "Governance preserve rule"

    if col_lower in FULL_MASK_COLUMNS:
        return "High", "Full Mask", "Governance full-mask rule"

    if col_lower in PARTIAL_MASK_COLUMNS:
        return "High", "Partial Mask", "Governance partial-mask rule"

    if entity in DIRECT_IDENTIFIER_ENTITIES and ratio >= 0.30:
        return "High", "Partial Mask", "Dynamic Presidio direct identifier detection"

    if entity in QUASI_IDENTIFIER_ENTITIES and ratio >= 0.50:
        return "Medium", "Preserve", "Quasi-identifier preserved for analytics utility"

    return "Non-sensitive", "Preserve", "No sensitive entity requiring masking"


def detect_privacy_risks(df: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    rows = []
    base_name = str(dataset_name).replace(".csv", "")
    for col in df.columns:
        entity, count, ratio, all_counts = analyze_column(df[col], col)
        sensitivity, action, reason = determine_sensitivity(col, entity, ratio)
        purview_class = map_to_purview_style_classification(entity, col)
        rows.append({
            "dataset_name": base_name,
            "column_name": col,
            "purview_style_classification": purview_class,
            "detected_entity": entity,
            "entity_detection_count": count,
            "entity_detection_ratio": round(ratio, 2),
            "all_detected_entities": str(all_counts),
            "sensitivity_level": sensitivity,
            "masking_action": action,
            "governance_reason": reason,
        })
    return pd.DataFrame(rows)


def partial_mask_email(value):
    if pd.isnull(value):
        return np.nan
    value = str(value)
    if "@" not in value:
        return "**"
    username, domain = value.split("@", 1)
    return (username[:2] + "**" if len(username) > 2 else username[:1] + "**") + "@" + domain


def partial_mask_phone(value):
    if pd.isnull(value):
        return np.nan
    value = str(value)
    return value[:3] + "**" + value[-2:] if len(value) >= 6 else "**"



def partial_mask_name(value):
    if pd.isnull(value):
        return np.nan
    value = str(value)
    if len(value) > 0:
        return value[0] + "**"
    return "**"


def generic_partial_mask(value):
    if pd.isnull(value):
        return np.nan
    value = str(value)
    if len(value) >= 4:
        return value[:2] + "**" + value[-1]
    return "**"


def mask_value(value, col: str, entity: str, action: str):
    col_lower = col.lower()
    if pd.isnull(value):
        return np.nan

    if action == "Preserve":
        return value

    if action == "Full Mask":
        return "***"

    if action == "Partial Mask":
        if col_lower == "nric" or entity == "MY_NRIC":
            return "***"
        if col_lower == "email" or entity == "EMAIL_ADDRESS":
            return partial_mask_email(value)
        if col_lower == "phone" or entity in ["PHONE_NUMBER", "MY_PHONE_NUMBER"]:
            return partial_mask_phone(value)
        if col_lower == "full_name" or entity == "PERSON":
            return partial_mask_name(value)
        if col_lower == "address":
            return "**"
        return generic_partial_mask(value)

    return value


def mask_sensitive_data(df: pd.DataFrame, privacy_report: pd.DataFrame) -> pd.DataFrame:
    masked = df.copy()
    for _, row in privacy_report.iterrows():
        col = row["column_name"]
        if col in masked.columns:
            masked[col] = masked[col].apply(lambda x: mask_value(x, col, row["detected_entity"], row["masking_action"]))
    return masked


def calculate_privacy_score(privacy_report: pd.DataFrame) -> float:
    if privacy_report.empty:
        return 0.0
    score = 0.0
    for _, row in privacy_report.iterrows():
        if row["sensitivity_level"] == "High":
            score += 1.5
        elif row["sensitivity_level"] == "Medium":
            score += 0.7
        if row["purview_style_classification"] in ["Malaysia NRIC", "Passport Number", "Credit Card Number", "Biometric Information"]:
            score += 1.0
    return round(min(score, 10.0), 1)


def recommend_classification(privacy_report: pd.DataFrame, quality_score: float) -> str:
    if privacy_report.empty:
        return "Internal"
    high = int((privacy_report["sensitivity_level"] == "High").sum())
    medium = int((privacy_report["sensitivity_level"] == "Medium").sum())
    restricted_classes = {"Malaysia NRIC", "Passport Number", "Credit Card Number", "Health Information", "Biometric Information"}
    has_restricted = "purview_style_classification" in privacy_report.columns and any(
        x in restricted_classes for x in privacy_report["purview_style_classification"].tolist()
    )
    categories = " ".join(privacy_report["detected_entity"].astype(str).tolist())
    if high >= 4 or (has_restricted and high >= 2):
        return "Highly Restricted"
    if has_restricted or high >= 2 or "Government Data" in categories:
        return "Restricted"
    if high >= 1 or medium >= 2 or "Financial Data" in categories:
        return "Confidential"
    if medium >= 1:
        return "Internal"
    return "Public"


def create_policy_summary(classification: str, privacy_score: float, is_paid: bool) -> Dict[str, str]:
    if classification == "Public":
        return {
            "access_policy": "Catalog access visible; purchase/access workflow still required",
            "masking_policy": "No masking required unless identifiers are detected",
            "retention_policy": "Standard retention",
            "approval_policy": "Auto publish allowed",
            "compliance_policy": "Basic audit logging",
        }
    if classification == "Internal":
        return {
            "access_policy": "Registered users only",
            "masking_policy": "Preserve business attributes; mask detected identifiers",
            "retention_policy": "Standard retention with owner review",
            "approval_policy": "Provider or MSP approval depending on tenant setting",
            "compliance_policy": "Audit access and downloads",
        }
    if classification == "Confidential":
        return {
            "access_policy": "Approval required; domain or organization restriction recommended",
            "masking_policy": "Apply partial masking for direct identifiers",
            "retention_policy": "Retention review required",
            "approval_policy": "MSP/manual approval recommended",
            "compliance_policy": "PDPA-aligned privacy review and audit logging",
        }
    if classification == "Restricted":
        return {
            "access_policy": "Manual approval required; token expiry enforced",
            "masking_policy": "Full/partial masking based on detected identifier type",
            "retention_policy": "Strict retention and deletion policy",
            "approval_policy": "Governance officer + MSP review",
            "compliance_policy": "PDPA-sensitive data controls and access traceability",
        }
    return {
        "access_policy": "Strict manual approval; limited access scope; short token expiry",
        "masking_policy": "Default full masking for regulated identifiers; release only masked sample",
        "retention_policy": "High-risk retention policy and periodic review",
        "approval_policy": "Governance officer approval mandatory",
        "compliance_policy": "High compliance monitoring, audit trail, and exception management",
    }


def quality_status_from_score(score: float) -> str:
    """Map a numerical quality score to the same status scale used in the Fabric notebook."""
    score = float(score or 0)
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Moderate"
    return "Poor"


def build_dataset_quality_scores(quality_report: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    """Build the dataset_quality_scores output dynamically for one processed dataset."""
    if not isinstance(quality_report, pd.DataFrame) or quality_report.empty:
        return pd.DataFrame([{
            "dataset_name": dataset_name,
            "completeness_score": 0.0,
            "validity_score": 0.0,
            "uniqueness_score": 0.0,
            "overall_quality_score": 0.0,
            "dataset_quality_status": "Poor",
        }])

    score_columns = [
        "completeness_score",
        "validity_score",
        "uniqueness_score",
        "overall_quality_score",
    ]
    available = [c for c in score_columns if c in quality_report.columns]
    if not available:
        return pd.DataFrame()

    scores = quality_report[available].apply(pd.to_numeric, errors="coerce").mean().round(2).to_dict()
    overall = float(scores.get("overall_quality_score", 0.0) or 0.0)
    row = {"dataset_name": dataset_name}
    for col in score_columns:
        row[col] = float(scores.get(col, 0.0) or 0.0)
    row["dataset_quality_status"] = quality_status_from_score(overall)
    return pd.DataFrame([row])


def build_processing_summary_report(
    raw_df: pd.DataFrame,
    cleaned_df: pd.DataFrame,
    quality_report: pd.DataFrame,
    privacy_report: pd.DataFrame,
    duplicate_count: int,
    dataset_name: str,
) -> pd.DataFrame:
    """Build the processing_summary_report output dynamically for one processed dataset."""
    original_rows, original_cols = raw_df.shape if isinstance(raw_df, pd.DataFrame) else (0, 0)
    cleaned_rows, cleaned_cols = cleaned_df.shape if isinstance(cleaned_df, pd.DataFrame) else (0, 0)

    quality_score = round(float(quality_report["overall_quality_score"].mean()), 2) if isinstance(quality_report, pd.DataFrame) and not quality_report.empty and "overall_quality_score" in quality_report.columns else 0.0

    high_sensitive_columns = 0
    masked_columns = 0
    preserved_columns = 0
    if isinstance(privacy_report, pd.DataFrame) and not privacy_report.empty:
        if "sensitivity_level" in privacy_report.columns:
            high_sensitive_columns = int((privacy_report["sensitivity_level"].astype(str) == "High").sum())
        if "masking_action" in privacy_report.columns:
            masking_actions = privacy_report["masking_action"].astype(str)
            masked_columns = int(masking_actions.isin(["Full Mask", "Partial Mask"]).sum())
            preserved_columns = int((masking_actions == "Preserve").sum())

    return pd.DataFrame([{
        "dataset_name": dataset_name,
        "original_rows": int(original_rows),
        "original_columns": int(original_cols),
        "cleaned_rows": int(cleaned_rows),
        "cleaned_columns": int(cleaned_cols),
        "duplicate_rows_removed": int(duplicate_count or 0),
        "dataset_quality_score": quality_score,
        "dataset_quality_status": quality_status_from_score(quality_score),
        "high_sensitive_columns": high_sensitive_columns,
        "masked_columns": masked_columns,
        "preserved_columns": preserved_columns,
    }])


def process_dataset(raw_df: pd.DataFrame, dataset_name: str, source_platform: str, fmt: str, source_uri: str = "") -> Dict:
    """
    Run the same core processing flow used by the Fabric notebook for any DataFrame:
    clean data, discover metadata, calculate quality, detect privacy risk, apply masking,
    and create the three report outputs shown in the catalog tabs.
    """
    cleaned_df, duplicate_count = clean_dataset(raw_df)
    metadata = discover_metadata(cleaned_df, dataset_name, source_platform, fmt, source_uri)
    quality_report = generate_quality_report(cleaned_df, dataset_name)
    privacy_report = detect_privacy_risks(cleaned_df, dataset_name)
    masked_df = mask_sensitive_data(cleaned_df, privacy_report)
    quality_score = round(float(quality_report["overall_quality_score"].mean()), 2) if not quality_report.empty else 0.0
    privacy_score = calculate_privacy_score(privacy_report)
    classification = recommend_classification(privacy_report, quality_score)
    dataset_quality_scores = build_dataset_quality_scores(quality_report, dataset_name)
    processing_summary_report = build_processing_summary_report(
        raw_df,
        cleaned_df,
        quality_report,
        privacy_report,
        duplicate_count,
        dataset_name,
    )
    return {
        "cleaned_df": cleaned_df,
        "masked_df": masked_df,
        "metadata": metadata,
        "quality_report": quality_report,
        "privacy_report": privacy_report,
        "dataset_quality_scores": dataset_quality_scores,
        "processing_summary_report": processing_summary_report,
        "quality_score": quality_score,
        "privacy_score": privacy_score,
        "classification": classification,
        "duplicate_count": duplicate_count,
    }


def normalize_dataset_key(name: str) -> str:
    return str(name).replace(".csv", "").strip().lower()


def load_processing_report_tables() -> Dict[str, pd.DataFrame]:
    reports = {}
    for key, filename in PROCESSING_REPORT_FILES.items():
        df = read_project_csv(filename)
        reports[key] = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    return reports


def get_report_for_dataset(report_key: str, dataset_name: str) -> pd.DataFrame:
    reports = st.session_state.get("processing_reports", {})
    df = reports.get(report_key, pd.DataFrame()) if isinstance(reports, dict) else pd.DataFrame()
    if not isinstance(df, pd.DataFrame) or df.empty or "dataset_name" not in df.columns:
        return pd.DataFrame()
    key = normalize_dataset_key(dataset_name)
    return df[df["dataset_name"].astype(str).str.replace(".csv", "", regex=False).str.lower().eq(key)].copy()


def apply_demo_processing_outputs(dataset_id: str, dataset_name: str) -> None:
    """Use Fabric-generated report CSVs and masked CSVs for the three demo datasets."""
    if dataset_id not in st.session_state.data_store:
        return

    masked_file = DEMO_MASKED_DATASET_FILES.get(str(dataset_name).lower())
    masked_df = read_project_csv(masked_file) if masked_file else None
    if isinstance(masked_df, pd.DataFrame) and not masked_df.empty:
        st.session_state.data_store[dataset_id]["masked"] = masked_df

    authorized_file = DEMO_AUTHORIZED_DATASET_FILES.get(str(dataset_name).lower())
    authorized_df = read_project_csv(authorized_file) if authorized_file else None
    if isinstance(authorized_df, pd.DataFrame) and not authorized_df.empty:
        st.session_state.data_store[dataset_id]["authorized"] = authorized_df

    privacy_df = get_report_for_dataset("privacy_masking_policy", dataset_name)
    if isinstance(privacy_df, pd.DataFrame) and not privacy_df.empty:
        if "purview_style_classification" not in privacy_df.columns:
            privacy_df.insert(2, "purview_style_classification", privacy_df.apply(
                lambda r: map_to_purview_style_classification(str(r.get("detected_entity", "None")), str(r.get("column_name", ""))),
                axis=1
            ))
        st.session_state.privacy_reports[dataset_id] = privacy_df

    quality_df = get_report_for_dataset("column_level_quality", dataset_name)
    if isinstance(quality_df, pd.DataFrame) and not quality_df.empty:
        st.session_state.quality_reports[dataset_id] = quality_df

    summary_df = get_report_for_dataset("processing_summary", dataset_name)
    quality_score_df = get_report_for_dataset("dataset_quality_scores", dataset_name)

    # For the three demo datasets, prefer the Fabric-generated CSV report outputs
    # when those files exist locally. If they are missing, the dynamic reports
    # already generated by process_dataset remain available.
    if "processing_outputs" not in st.session_state or not isinstance(st.session_state.processing_outputs, dict):
        st.session_state.processing_outputs = {}
    existing_outputs = st.session_state.processing_outputs.get(dataset_id, {})
    st.session_state.processing_outputs[dataset_id] = {
        "dataset_quality_scores": quality_score_df if not quality_score_df.empty else existing_outputs.get("dataset_quality_scores", pd.DataFrame()),
        "column_level_quality": quality_df if not quality_df.empty else existing_outputs.get("column_level_quality", pd.DataFrame()),
        "privacy_masking_policy": privacy_df if not privacy_df.empty else existing_outputs.get("privacy_masking_policy", pd.DataFrame()),
        "processing_summary": summary_df if not summary_df.empty else existing_outputs.get("processing_summary", pd.DataFrame()),
    }

    if not summary_df.empty:
        s = summary_df.iloc[0]
        idx = st.session_state.datasets[st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)].index
        if len(idx):
            st.session_state.datasets.loc[idx, "rows"] = int(s.get("cleaned_rows", st.session_state.datasets.loc[idx, "rows"].iloc[0]))
            st.session_state.datasets.loc[idx, "columns"] = int(s.get("cleaned_columns", st.session_state.datasets.loc[idx, "columns"].iloc[0]))
            st.session_state.datasets.loc[idx, "quality_score"] = float(s.get("dataset_quality_score", st.session_state.datasets.loc[idx, "quality_score"].iloc[0]))

    if not quality_score_df.empty:
        qs = quality_score_df.iloc[0]
        idx = st.session_state.datasets[st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)].index
        if len(idx):
            st.session_state.datasets.loc[idx, "quality_score"] = float(qs.get("overall_quality_score", st.session_state.datasets.loc[idx, "quality_score"].iloc[0]))

    meta = st.session_state.metadata_store.get(dataset_id, {})
    meta["Processing Outputs"] = json.dumps({
        "masked_dataset_file": masked_file or "",
        "processing_summary_report": PROCESSING_REPORT_FILES["processing_summary"],
        "privacy_and_masking_policy_report": PROCESSING_REPORT_FILES["privacy_masking_policy"],
        "dataset_quality_scores": PROCESSING_REPORT_FILES["dataset_quality_scores"],
        "column_level_quality_report": PROCESSING_REPORT_FILES["column_level_quality"],
    })
    st.session_state.metadata_store[dataset_id] = meta

# =============================================================================
# Session state initialization
# =============================================================================

def init_state() -> None:
    if "initialized" in st.session_state:
        return

    if load_prototype_state():
        if "current_user" not in st.session_state:
            st.session_state.current_user = None
        st.session_state.initialized = True
        return

    tenants = pd.DataFrame([
        {"tenant_id": "T-MSP", "tenant_name": "Credence", "tenant_type": "MSP", "requires_msp_approval": False, "status": "Active", "created_at": today_str()},
        {"tenant_id": "T-OWNER-DEMO", "tenant_name": "TM One", "tenant_type": "Data Provider", "requires_msp_approval": True, "status": "Active", "created_at": today_str()},
        {"tenant_id": "T-CONSUMER-DEMO", "tenant_name": "PSM UMPSA", "tenant_type": "Data Consumer", "requires_msp_approval": False, "status": "Active", "created_at": today_str()},
    ])

    users = pd.DataFrame([
        {"email": "admin@credence.my", "name": "Credence MSP Admin", "password_hash": hash_password("admin123"),
         "role": "MSP Administrator", "tenant_id": "T-MSP", "status": "Active"},
        {"email": "gov@credence.my", "name": "Credence Governance Admin", "password_hash": hash_password("gov123"),
         "role": "Governance Administrator", "tenant_id": "T-MSP", "status": "Active"},
        {"email": "market@credence.my", "name": "Credence Marketplace Admin",
         "password_hash": hash_password("market123"), "role": "Marketplace Administrator", "tenant_id": "T-MSP",
         "status": "Active"},
        {"email": "catalog@credence.my", "name": "Credence Catalog Admin", "password_hash": hash_password("catalog123"),
         "role": "Catalog Administrator", "tenant_id": "T-MSP", "status": "Active"},
        {"email": "operator@credence.my", "name": "Credence Platform Operator",
         "password_hash": hash_password("operator123"), "role": "Platform Operator", "tenant_id": "T-MSP",
         "status": "Active"},

        {"email": "provider@tmone.my", "name": "TM One Provider Administrator", "password_hash": hash_password("provider123"),
         "role": "Provider Administrator", "tenant_id": "T-OWNER-DEMO", "status": "Active"},
        {"email": "owner@tmone.my", "name": "TM One Data Owner", "password_hash": hash_password("owner123"),
         "role": "Data Owner", "tenant_id": "T-OWNER-DEMO", "status": "Active"},
        {"email": "steward@tmone.my", "name": "TM One Data Steward", "password_hash": hash_password("steward123"),
         "role": "Data Steward", "tenant_id": "T-OWNER-DEMO", "status": "Active"},
        {"email": "contributor@tmone.my", "name": "TM One Data Contributor",
         "password_hash": hash_password("contributor123"), "role": "Data Contributor", "tenant_id": "T-OWNER-DEMO",
         "status": "Active"},

        {"email": "admin@psm.umpsa.my", "name": "PSM Administrator", "password_hash": hash_password("consumer123"),
         "role": "Consumer Administrator", "tenant_id": "T-CONSUMER-DEMO", "status": "Active"},
        {"email": "researcher@psm.umpsa.my", "name": "PSM Researcher", "password_hash": hash_password("user123"),
         "role": "Consumer User", "tenant_id": "T-CONSUMER-DEMO", "status": "Active"},
    ])

    st.session_state.tenants = tenants
    st.session_state.users = users
    st.session_state.datasets = pd.DataFrame(columns=[
        "dataset_id", "dataset_name", "description", "owner_email", "owner_tenant_id", "registration_method",
        "source_platform", "format", "source_uri", "classification", "quality_score", "privacy_score",
        "rows", "columns", "size_kb", "price_rm", "is_paid", "status", "approval_required",
        "created_at", "approved_by", "approved_at", "download_count", "revenue_rm", "msp_commission_rate",
        "msp_commission_rm", "provider_revenue_rm", "tags", "provider_internal_note",
        "storage_platform", "fabric_workspace", "lakehouse_name", "fabric_path", "fabric_url", "onelake_url", "abfss_path",
    ])
    st.session_state.metadata_store = {}
    st.session_state.data_store = {}
    st.session_state.quality_reports = {}
    st.session_state.privacy_reports = {}
    st.session_state.policies = pd.DataFrame(columns=["policy_id", "policy_type", "policy_name", "rule", "enabled"])
    st.session_state.access_requests = pd.DataFrame(columns=[
        "request_id", "dataset_id", "dataset_name", "consumer_email", "consumer_tenant_id", "purpose", "status",
        "payment_status",
        "amount_rm", "msp_commission_rate", "msp_commission_rm", "provider_revenue_rm", "created_at", "reviewed_by",
        "reviewed_at",
    ])
    st.session_state.tokens = pd.DataFrame(columns=[
        "token", "dataset_id", "dataset_name", "consumer_email", "consumer_tenant_id", "permission", "expiry", "status",
        "created_at",
    ])
    st.session_state.governance_alerts = pd.DataFrame(columns=[
        "alert_id", "dataset_id", "dataset_name", "triggered_by", "check_type", "severity", "status", "created_at",
        "finding", "recommended_action",
    ])
    st.session_state.audit_log = pd.DataFrame(columns=["Time", "Actor", "Tenant", "Action"])
    st.session_state.current_user = None
    st.session_state.processing_reports = load_processing_report_tables()
    st.session_state.processing_outputs = {}
    st.session_state.payment_transactions = pd.DataFrame(columns=[
        "transaction_id", "request_id", "dataset_id", "dataset_name", "consumer_email",
        "payment_method", "gateway", "amount_rm", "msp_commission_rm", "provider_revenue_rm",
        "gateway_status", "authorization_code", "paid_at",
    ])
    ensure_review_tracking_columns()
    st.session_state.initialized = True
    _ = preload_demo_datasets()


def tenant_name(tenant_id: str) -> str:
    t = st.session_state.tenants[st.session_state.tenants["tenant_id"] == tenant_id]
    return t.iloc[0]["tenant_name"] if not t.empty else tenant_id


def get_current_user() -> Optional[Dict]:
    return st.session_state.get("current_user")


def roles_for_tenant_type(tenant_type: str) -> List[str]:
    return ROLE_GROUPS.get(tenant_type, [])


def role_tenant_type(role: str) -> str:
    for tenant_type, roles in ROLE_GROUPS.items():
        if role in roles:
            return tenant_type
    return "Unknown"


def is_msp_role(role: str) -> bool:
    return role in MSP_ROLES


def is_governance_role(role: str) -> bool:
    return role in ["Governance Administrator", "Catalog Administrator", "MSP Administrator"]


def is_provider_role(role: str) -> bool:
    return role in PROVIDER_ROLES


def is_consumer_role(role: str) -> bool:
    return role in CONSUMER_ROLES


def can_manage_tenants(role: str) -> bool:
    return role == "MSP Administrator"


def can_manage_provider_settings(role: str) -> bool:
    return role == "MSP Administrator"


def can_review_dataset(role: str) -> bool:
    return role in ["MSP Administrator", "Governance Administrator", "Catalog Administrator"]


def can_manage_policies(role: str) -> bool:
    return role in ["MSP Administrator", "Governance Administrator"]


def can_manage_marketplace(role: str) -> bool:
    return role in ["MSP Administrator", "Marketplace Administrator"]


def can_register_dataset(role: str) -> bool:
    return role in ["Provider Administrator", "Data Owner", "Data Contributor"]


def can_approve_provider_request(role: str) -> bool:
    return role in ["Provider Administrator", "Data Owner"]


def get_user_tenant_type(user: Dict) -> str:
    t = st.session_state.tenants[st.session_state.tenants["tenant_id"] == user["tenant_id"]]
    if t.empty:
        return role_tenant_type(user["role"])
    return str(t.iloc[0]["tenant_type"])



def get_provider_setting(tenant_id: str) -> bool:
    t = st.session_state.tenants[st.session_state.tenants["tenant_id"] == tenant_id]
    if t.empty:
        return True
    return bool(t.iloc[0]["requires_msp_approval"])


def fabric_reference_for_file(filename: str) -> Dict[str, str]:
    """Return Microsoft Fabric/OneLake storage reference for a demo file."""
    filename = filename.strip()
    relative_path = f"{FABRIC_RELATIVE_FOLDER}/{filename}"
    encoded_path = relative_path.replace("/", "%2F")
    return {
        "storage_platform": "Microsoft Fabric Lakehouse",
        "fabric_workspace": FABRIC_WORKSPACE_NAME,
        "lakehouse_name": FABRIC_LAKEHOUSE_NAME,
        "fabric_path": relative_path,
        "fabric_url": (
            f"https://app.fabric.microsoft.com/groups/{FABRIC_WORKSPACE_ID}/lakehouses/{FABRIC_LAKEHOUSE_ID}"
            f"?experience=fabric-developer&selectedPath={encoded_path}"
        ),
        "onelake_url": f"{FABRIC_ONELAKE_FOLDER_URL}/{filename}",
        "abfss_path": f"{FABRIC_ABFSS_FOLDER_PATH}/{filename}",
    }


def add_dataset_record(
        dataset_name: str, description: str, owner_email: str, owner_tenant_id: str, registration_method: str,
        source_platform: str, fmt: str, source_uri: str, processed: Dict, price_rm: float, is_paid: bool, tags: str,
        provider_internal_note: str = "", storage_platform: str = "", fabric_workspace: str = "",
        lakehouse_name: str = "",
        fabric_path: str = "", fabric_url: str = "", onelake_url: str = "", abfss_path: str = "",
        status: Optional[str] = None, approved_by: str = ""
) -> str:
    dataset_id = generate_id("DS")
    approval_required = get_provider_setting(owner_tenant_id)

    if status is None:
        status = "Draft"
        approved_by = ""

    meta = processed["metadata"]
    if not storage_platform and dataset_name in DEMO_DATASET_FILES:
        ref = fabric_reference_for_file(dataset_name)
        storage_platform = ref["storage_platform"]
        fabric_workspace = ref["fabric_workspace"]
        lakehouse_name = ref["lakehouse_name"]
        fabric_path = ref["fabric_path"]
        fabric_url = ref["fabric_url"]
        onelake_url = ref["onelake_url"]
        abfss_path = ref["abfss_path"]

    row = pd.DataFrame([{
        "dataset_id": dataset_id, "dataset_name": dataset_name, "description": description, "owner_email": owner_email,
        "owner_tenant_id": owner_tenant_id, "registration_method": registration_method,
        "source_platform": source_platform,
        "format": fmt, "source_uri": source_uri, "classification": processed["classification"],
        "quality_score": processed["quality_score"],
        "privacy_score": processed["privacy_score"], "rows": meta.get("Rows", 0), "columns": meta.get("Columns", 0),
        "size_kb": meta.get("Size Estimate KB", 0), "price_rm": float(price_rm), "is_paid": bool(is_paid),
        "status": status,
        "approval_required": bool(approval_required), "created_at": today_str(), "approved_by": approved_by,
        "approved_at": today_str() if status == "Published" else "", "download_count": 0, "revenue_rm": 0.0,
        "msp_commission_rate": MSP_COMMISSION_RATE, "msp_commission_rm": 0.0, "provider_revenue_rm": 0.0, "tags": tags,
        "provider_internal_note": provider_internal_note, "storage_platform": storage_platform,
        "fabric_workspace": fabric_workspace,
        "lakehouse_name": lakehouse_name, "fabric_path": fabric_path, "fabric_url": fabric_url,
        "onelake_url": onelake_url, "abfss_path": abfss_path,
    }])
    if st.session_state.datasets.empty:
        st.session_state.datasets = row.copy()
    else:
        st.session_state.datasets = pd.concat([st.session_state.datasets, row], ignore_index=True)
    st.session_state.metadata_store[dataset_id] = processed["metadata"]
    st.session_state.data_store[dataset_id] = {"cleaned": processed["cleaned_df"], "masked": processed["masked_df"]}
    st.session_state.quality_reports[dataset_id] = processed["quality_report"]
    st.session_state.privacy_reports[dataset_id] = processed["privacy_report"]
    if "processing_outputs" not in st.session_state or not isinstance(st.session_state.processing_outputs, dict):
        st.session_state.processing_outputs = {}
    st.session_state.processing_outputs[dataset_id] = {
        "dataset_quality_scores": processed.get("dataset_quality_scores", pd.DataFrame()),
        "column_level_quality": processed.get("quality_report", pd.DataFrame()),
        "privacy_masking_policy": processed.get("privacy_report", pd.DataFrame()),
        "processing_summary": processed.get("processing_summary_report", pd.DataFrame()),
    }
    policy = create_policy_summary(processed["classification"], processed["privacy_score"], is_paid)
    st.session_state.metadata_store[dataset_id]["Governance Policies"] = json.dumps(policy)
    st.session_state.metadata_store[dataset_id]["Storage Platform"] = storage_platform
    st.session_state.metadata_store[dataset_id]["Fabric Workspace"] = fabric_workspace
    st.session_state.metadata_store[dataset_id]["Lakehouse Name"] = lakehouse_name
    st.session_state.metadata_store[dataset_id]["Fabric Path"] = fabric_path
    st.session_state.metadata_store[dataset_id]["Fabric Portal URL"] = fabric_url
    st.session_state.metadata_store[dataset_id]["OneLake URL"] = onelake_url
    st.session_state.metadata_store[dataset_id]["ABFSS Path"] = abfss_path
    st.session_state.metadata_store[dataset_id]["Provider Internal Note"] = provider_internal_note

    save_prototype_state()
    return dataset_id


def local_dataset_path(filename: str) -> Optional[str]:
    """Return the local path for a dataset/report file placed beside this app or in the current working directory."""
    return find_project_file(filename)


def load_project_dataset_file(filename: str) -> Optional[pd.DataFrame]:
    """Load the actual synthetic CSV used in Fabric and the report. No coded fallback data is used."""
    return read_project_csv(filename)


def default_registration_method_for_source(source_platform: str) -> str:
    if source_platform in ["CSV File", "Excel File", "Parquet File", "JSON File"]:
        return "File Upload"
    if source_platform in ["PostgreSQL", "Oracle", "MySQL", "Iceberg Table"]:
        return "Database Connection"
    if source_platform in ["REST API", "GraphQL API"]:
        return "API Endpoint"
    return "External Storage URL"


def ordered_registration_methods(source_platform: str) -> List[str]:
    default = default_registration_method_for_source(source_platform)
    return [default] + [m for m in REGISTRATION_METHODS if m != default]


def preload_demo_datasets() -> None:
    if len(st.session_state.datasets) > 0:
        return

    demo_descriptions = {
        "customer.csv": "Synthetic customer dataset related to telecommunication subscribers containing demographics, plan details, and status.",
        "billing.csv": "Synthetic billing and payment dataset related to telecommunication revenue tracking.",
        "service.csv": "Synthetic service subscription dataset detailing network performance, access technology and router models.",
    }
    demo_prices = {
        "customer.csv": 120.0,
        "billing.csv": 80.0,
        "service.csv": 60.0,
    }
    demo_tags = {
        "customer.csv": "Customer, Telecommunications, Customer Segmentation, Malaysia",
        "billing.csv": "Billing, Telecommunications, Revenue Analysis, Payment Behaviour Analysis, Malaysia",
        "service.csv": "Service, Network, Telecommunications, Network Performance Analysis, Service Assurance, Malaysia",
    }

    loaded_files = []
    missing_files = []
    for filename in DEMO_DATASET_FILES:
        df = load_project_dataset_file(filename)
        if df is None:
            _ = missing_files.append(filename)
            continue

        fabric_ref = fabric_reference_for_file(filename)
        processed = process_dataset(df, filename, "Microsoft Fabric Lakehouse", "CSV", fabric_ref["onelake_url"])
        dataset_id = add_dataset_record(
            dataset_name=filename,
            description=demo_descriptions[filename],
            owner_email="provider@tmone.my",
            owner_tenant_id="T-OWNER-DEMO",
            registration_method="External Storage URL",
            source_platform="Microsoft Fabric Lakehouse",
            fmt="CSV",
            source_uri=fabric_ref["onelake_url"],
            processed=processed,
            price_rm=demo_prices[filename],
            is_paid=True,
            tags=demo_tags[filename],
            provider_internal_note="Preloaded from local synthetic CSV file and linked to the matching Microsoft Fabric Lakehouse storage reference. Demo masked sample and processing reports are loaded from the Fabric-generated CSV outputs when available.",
            storage_platform=fabric_ref["storage_platform"],
            fabric_workspace=fabric_ref["fabric_workspace"],
            lakehouse_name=fabric_ref["lakehouse_name"],
            fabric_path=fabric_ref["fabric_path"],
            fabric_url=fabric_ref["fabric_url"],
            onelake_url=fabric_ref["onelake_url"],
            abfss_path=fabric_ref["abfss_path"],
            status="Published",
            approved_by="Demo preload",
        )
        apply_demo_processing_outputs(dataset_id, filename)
        _ = loaded_files.append(filename)

    if loaded_files:
        _ = add_log("System", f"Preloaded local synthetic datasets: {', '.join(loaded_files)}", "T-MSP")
    if missing_files:
        _ = add_log("System", f"Local synthetic dataset files missing: {', '.join(missing_files)}", "T-MSP")

init_state()

# =============================================================================
# Authentication screens
# =============================================================================
def login_screen():
    st.image("Credence_full_logo.png", width=180)
    _ = show_header(APP_NAME, APP_SUBTITLE)

    tab_login, tab_signup, tab_accounts = st.tabs(["Log in", "Sign up", "Demo accounts"])

    with tab_login:
        st.subheader("Log in")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Log in", type="primary"):
            users = st.session_state.users
            match = users[(users["email"].str.lower() == email.lower()) & (users["status"] == "Active")]
            if match.empty:
                st.error("Invalid email or inactive account.")
            elif not verify_password(password, match.iloc[0]["password_hash"]):
                st.error("Invalid password.")
            else:
                user = match.iloc[0].to_dict()
                st.session_state.current_user = user

                st.session_state.current_page = None

                _ = add_log(user["email"], f"Logged in as {user['role']}", user["tenant_id"])
                st.rerun()

    with tab_signup:
        st.subheader("Create new account")
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Full name")
            new_email = st.text_input("Email address")
            new_password = st.text_input("Password", type="password")
        with c2:
            signup_tenant_type = st.selectbox("Account type", ["Data Provider", "Data Consumer"])
            tenant_name_input = st.text_input("Organization / Tenant name")
            role = "Provider Administrator" if signup_tenant_type == "Data Provider" else "Consumer Administrator"
            tenant_type = signup_tenant_type
        if st.button("Sign up account"):
            if not name or not new_email or not new_password or not tenant_name_input:
                st.warning("Please fill in all required fields.")
            elif new_email.lower() in st.session_state.users["email"].str.lower().tolist():
                st.error("Email already exists.")
            else:
                tenant_id = generate_id("T")
                new_tenant = pd.DataFrame([{
                    "tenant_id": tenant_id,
                    "tenant_name": tenant_name_input,
                    "tenant_type": tenant_type,
                    "requires_msp_approval": True if tenant_type == "Data Provider" else False,
                    "status": "Active",
                    "created_at": today_str(),
                }])
                new_user = pd.DataFrame([{
                    "email": new_email.lower(),
                    "name": name,
                    "password_hash": hash_password(new_password),
                    "role": role,
                    "tenant_id": tenant_id,
                    "status": "Active",
                }])
                st.session_state.tenants = pd.concat([st.session_state.tenants, new_tenant], ignore_index=True)
                st.session_state.users = pd.concat([st.session_state.users, new_user], ignore_index=True)
                _ = add_log(new_email.lower(), f"Signed up as {role} under {tenant_type} tenant; tenant created with relevant MSP approval setting", tenant_id)
                st.success("Account created. You may now log in.")

    with tab_accounts:
        st.subheader("Platform Stakeholders")

        hierarchy = pd.DataFrame([
            ["MSP", "Own and operate the platform"],
            ["Data Provider", "Publish and monetize datasets"],
            ["Data Consumer", "Discover, request and consume datasets"]
        ],
            columns=["Tenant Category", "Purpose"])

        st.dataframe(
            hierarchy,
            width="stretch",
            hide_index=True
        )

        st.subheader("Demo Accounts & Role Reference")

        demo = pd.DataFrame([
            ["MSP", "MSP Administrator", "admin@credence.my", "admin123",
             "Highest platform role. Manages tenants, users, provider approval settings, policies, datasets, access requests and audit logs."],

            ["MSP", "Governance Administrator", "gov@credence.my", "gov123",
             "Reviews privacy scan results, sensitivity classification, compliance policies and high-risk dataset approval."],

            ["MSP", "Marketplace Administrator", "market@credence.my", "market123",
             "Manages paid/free catalog publication, consumer access requests, payment simulation and revenue monitoring."],

            ["MSP", "Catalog Administrator", "catalog@credence.my", "catalog123",
             "Curates catalog metadata, tags, glossary information, dataset publication readiness and catalog quality."],

            ["MSP", "Platform Operator", "operator@credence.my", "operator123",
             "Monitors governance alerts, policy findings, access anomalies, catalog compliance and platform audit activity."],

            ["Data Provider", "Provider Administrator", "provider@tmone.my", "provider123",
             "Manages TM One provider users, registers telecom datasets, configures pricing and oversees provider publication workflow."],

            ["Data Provider", "Data Owner", "owner@tmone.my", "owner123",
             "Owns TM One datasets, submits publication requests, approves consumer requests and defines dataset access intent."],

            ["Data Provider", "Data Steward", "steward@tmone.my", "steward123",
             "Maintains TM One metadata quality, tags, descriptions, classifications and governance readiness."],

            ["Data Provider", "Data Contributor", "contributor@tmone.my", "contributor123",
             "Registers TM One datasets and triggers metadata, privacy and quality scans but cannot publish or approve access."],

            ["Data Consumer", "Consumer Administrator", "admin@psm.umpsa.my", "consumer123",
             "Manages PSM dataset usage, purchases or requests datasets and monitors organization access tokens."],

            ["Data Consumer", "Consumer User", "researcher@psm.umpsa.my", "user123",
             "Browses the published catalog, requests access and downloads authorized datasets for PSM research use."]
        ],
            columns=[
                "Tenant Category",
                "Role",
                "Email",
                "Password",
                "Primary Responsibilities"
            ])

        st.dataframe(
            demo,
            width="stretch",
            hide_index=True
        )

# =============================================================================
# Shared components
# =============================================================================


def visible_datasets_for_user(user: Dict) -> pd.DataFrame:
    df = st.session_state.datasets.copy()
    if is_msp_role(user["role"]):
        return df[df["status"].astype(str) != "Draft"]
    if is_provider_role(user["role"]):
        return df[df["owner_tenant_id"] == user["tenant_id"]]
    # Consumer sees only published datasets in marketplace.
    return df[df["status"] == "Published"]

# =============================================================================
# MSP Admin pages
# =============================================================================




def page_provider_approval_settings():
    _ = show_header("Provider Approval Settings", "MSP can control whether each data provider requires manual approval before publication.")
    providers = st.session_state.tenants[st.session_state.tenants["tenant_type"] == "Data Provider"].copy()
    st.info("Default rule: when a data provider registers a dataset using their own account, the dataset requires MSP approval. MSP may untick this for trusted providers.")
    edited = st.data_editor(
        providers,
        width="stretch",
        hide_index=True,
        column_config={"requires_msp_approval": st.column_config.CheckboxColumn("Manual MSP Approval Required")},
        key="provider_approval_editor",
    )
    if st.button("Save provider approval settings"):
        for _, row in edited.iterrows():
            idx = st.session_state.tenants[st.session_state.tenants["tenant_id"] == row["tenant_id"]].index
            if len(idx):
                st.session_state.tenants.loc[idx, "requires_msp_approval"] = bool(row["requires_msp_approval"])
        _ = add_log(get_current_user()["email"], "Updated per-provider approval requirements", get_current_user()["tenant_id"])
        st.success("Provider approval settings updated.")


def page_dataset_approval_queue():
    _ = show_header("Dataset Approval Queue", "Approve or reject provider-submitted datasets before they are published to the catalog.")
    pending = st.session_state.datasets[st.session_state.datasets["status"].isin(["Submitted", "Privacy Review", "MSP Review"])]
    if pending.empty:
        st.success("No pending datasets requiring action.")
        return
    for _, row in pending.iterrows():
        with st.expander(f"{row['dataset_name']} | {tenant_name(row['owner_tenant_id'])} | {row['classification']} | {row['status']}"):
            _ = render_dataset_detail(row["dataset_id"], allow_data_preview=True)




def page_governance_monitoring():
    _ = show_header("Governance Monitoring & Alerts", "MSP monitoring view for policy checks, compliance findings and catalog governance review.")

    st.markdown("""
    <div class='small-note'>
    This page does not simulate MSP manually running every provider's Fabric pipeline or notebook.
    Instead, it represents the MSP governance monitoring layer: the platform scans catalog metadata,
    approval status, quality scores, privacy risk, access requests and token activity, then surfaces
    findings that require MSP review.
    </div>
    """, unsafe_allow_html=True)

    if "governance_alerts" not in st.session_state or not isinstance(st.session_state.governance_alerts, pd.DataFrame):
        st.session_state.governance_alerts = pd.DataFrame(columns=[
            "alert_id", "dataset_id", "dataset_name", "triggered_by", "check_type", "severity",
            "status", "created_at", "finding", "recommended_action",
        ])

    datasets = st.session_state.datasets.copy()
    access_requests = st.session_state.access_requests.copy() if "access_requests" in st.session_state else pd.DataFrame()
    tokens = st.session_state.tokens.copy() if "tokens" in st.session_state else pd.DataFrame()

    c1, c2, c3 = st.columns(3)
    selected_check = c1.selectbox(
        "Monitoring check",
        [
            "Full governance scan",
            "Catalog metadata completeness",
            "Privacy and sensitivity risk",
            "Quality threshold review",
            "Access and token compliance",
        ],
    )
    severity_threshold = c2.selectbox("Minimum severity to display", ["Low", "Medium", "High"], index=0)
    auto_create = c3.checkbox("Create review alerts", value=True)

    def severity_rank(value: str) -> int:
        return {"Low": 1, "Medium": 2, "High": 3}.get(str(value), 1)

    def build_alerts() -> pd.DataFrame:
        findings = []

        for _, dataset in datasets.iterrows():
            dataset_id = str(dataset.get("dataset_id", ""))
            dataset_name = str(dataset.get("dataset_name", ""))
            title = str(dataset.get("catalog_title", "") or dataset_name)
            tags = str(dataset.get("tags", "") or "")
            description = str(dataset.get("description", "") or "")
            quality_score = _num(dataset.get("quality_score", 0))
            privacy_score = _num(dataset.get("privacy_score", 0))
            status = str(dataset.get("status", ""))

            if selected_check in ["Full governance scan", "Catalog metadata completeness"]:
                if not tags.strip() or not description.strip():
                    findings.append({
                        "alert_id": generate_id("ALT"),
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "triggered_by": get_current_user()["email"],
                        "check_type": "Catalog metadata completeness",
                        "severity": "Medium",
                        "status": "Open",
                        "created_at": now_str(),
                        "finding": f"{title} has incomplete catalog metadata such as missing description or business tags.",
                        "recommended_action": "Ask the data provider to complete business description and business-friendly tags before or after publication.",
                    })

            if selected_check in ["Full governance scan", "Privacy and sensitivity risk"]:
                if privacy_score >= 7:
                    findings.append({
                        "alert_id": generate_id("ALT"),
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "triggered_by": get_current_user()["email"],
                        "check_type": "Privacy and sensitivity risk",
                        "severity": "High",
                        "status": "Open",
                        "created_at": now_str(),
                        "finding": f"{title} has high privacy risk score ({privacy_score}).",
                        "recommended_action": "Review the privacy and masking policy report before approving or keeping the asset published.",
                    })

            if selected_check in ["Full governance scan", "Quality threshold review"]:
                if quality_score and quality_score < 75:
                    findings.append({
                        "alert_id": generate_id("ALT"),
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "triggered_by": get_current_user()["email"],
                        "check_type": "Quality threshold review",
                        "severity": "Medium",
                        "status": "Open",
                        "created_at": now_str(),
                        "finding": f"{title} quality score is below threshold ({quality_score:.2f}%).",
                        "recommended_action": "Request provider remediation or add a catalog warning before consumer purchase.",
                    })

            if selected_check in ["Full governance scan", "Catalog metadata completeness"]:
                if status == "Published" and not str(dataset.get("approved_by", "")).strip():
                    findings.append({
                        "alert_id": generate_id("ALT"),
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "triggered_by": get_current_user()["email"],
                        "check_type": "Publication approval traceability",
                        "severity": "Medium",
                        "status": "Open",
                        "created_at": now_str(),
                        "finding": f"{title} is published but approval traceability is incomplete.",
                        "recommended_action": "Confirm approver and approval timestamp are properly recorded for audit evidence.",
                    })

        if selected_check in ["Full governance scan", "Access and token compliance"] and not tokens.empty:
            active_tokens = tokens[tokens.get("status", pd.Series(dtype=str)).astype(str).eq("Active")].copy()
            if "expiry" in active_tokens.columns:
                for _, token_row in active_tokens.iterrows():
                    expiry_value = pd.to_datetime(token_row.get("expiry", ""), errors="coerce")
                    if pd.notna(expiry_value) and expiry_value < pd.Timestamp.now():
                        findings.append({
                            "alert_id": generate_id("ALT"),
                            "dataset_id": str(token_row.get("dataset_id", "")),
                            "dataset_name": str(token_row.get("dataset_name", "")),
                            "triggered_by": get_current_user()["email"],
                            "check_type": "Access and token compliance",
                            "severity": "High",
                            "status": "Open",
                            "created_at": now_str(),
                            "finding": f"Expired token is still marked Active for {token_row.get('dataset_name', '')}.",
                            "recommended_action": "Revoke the token or refresh its status for accurate access governance.",
                        })

        if selected_check in ["Full governance scan", "Access and token compliance"] and not access_requests.empty:
            stale_pending = access_requests[
                access_requests["status"].astype(str).isin(["Pending Provider Approval", "Pending Provider/MSP Approval"])
            ].copy()
            if not stale_pending.empty:
                for _, request_row in stale_pending.iterrows():
                    findings.append({
                        "alert_id": generate_id("ALT"),
                        "dataset_id": str(request_row.get("dataset_id", "")),
                        "dataset_name": str(request_row.get("dataset_name", "")),
                        "triggered_by": get_current_user()["email"],
                        "check_type": "Access request review",
                        "severity": "Low",
                        "status": "Open",
                        "created_at": now_str(),
                        "finding": f"Access request {request_row.get('request_id', '')} is still waiting for provider or MSP review.",
                        "recommended_action": "Follow up with the responsible provider or marketplace administrator.",
                    })

        result = pd.DataFrame(findings)
        if not result.empty:
            result = result[result["severity"].apply(severity_rank) >= severity_rank(severity_threshold)].copy()
        return result

    if st.button("Run governance monitoring scan", type="primary"):
        new_alerts = build_alerts()
        if new_alerts.empty:
            st.success("Scan completed. No governance issues found for the selected check.")
        else:
            if auto_create:
                st.session_state.governance_alerts = pd.concat(
                    [st.session_state.governance_alerts, new_alerts],
                    ignore_index=True,
                )
                _ = add_log(get_current_user()["email"], f"Created {len(new_alerts)} governance monitoring alert(s)", get_current_user()["tenant_id"])
                st.warning(f"Scan completed. {len(new_alerts)} alert(s) created for MSP review.")
            else:
                st.warning(f"Scan completed. {len(new_alerts)} finding(s) found.")
                st.dataframe(new_alerts, width="stretch", hide_index=True)

    alerts = st.session_state.governance_alerts.copy()
    if alerts.empty:
        st.info("No governance alerts yet. Run a monitoring scan to generate MSP review findings.")
        return

    open_alerts = alerts[alerts["status"].astype(str).eq("Open")] if "status" in alerts.columns else alerts
    high_alerts = alerts[alerts["severity"].astype(str).eq("High")] if "severity" in alerts.columns else pd.DataFrame()
    c1, c2, c3 = st.columns(3)
    c1.metric("Open Alerts", len(open_alerts))
    c2.metric("High Severity", len(high_alerts))
    c3.metric("Total Findings", len(alerts))

    st.subheader("Governance Review Findings")
    st.dataframe(alerts.sort_values("created_at", ascending=False), width="stretch", hide_index=True)

    alert_options = alerts[alerts["status"].astype(str).eq("Open")]["alert_id"].tolist()
    if alert_options:
        selected_alert = st.selectbox("Resolve alert", alert_options)
        resolution_note = st.text_area("Resolution note", key="governance_alert_resolution_note")
        if st.button("Mark alert as resolved"):
            idx = st.session_state.governance_alerts[
                st.session_state.governance_alerts["alert_id"].astype(str) == str(selected_alert)
            ].index
            if len(idx):
                st.session_state.governance_alerts.loc[idx, "status"] = "Resolved"
                if "recommended_action" in st.session_state.governance_alerts.columns and resolution_note.strip():
                    st.session_state.governance_alerts.loc[idx, "recommended_action"] = resolution_note.strip()
                _ = add_log(get_current_user()["email"], f"Resolved governance alert {selected_alert}", get_current_user()["tenant_id"])
                st.success("Alert marked as resolved.")
                st.rerun()



def page_audit_log():
    _ = show_header("Audit Log", "Traceability for login, registration, approval, policy and access events.")
    st.dataframe(st.session_state.audit_log.sort_values("Time", ascending=False), width="stretch", hide_index=True)
    _ = dataframe_download_button(st.session_state.audit_log, "Export audit log", "audit_log.csv", key="dl_audit_log_main")

# =============================================================================
# Governance Officer pages
# =============================================================================
def page_governance_dashboard():
    _ = ensure_enhanced_state()
    _ = show_header("Governance Dashboard", "Governance health, sensitivity distribution, policy risk and compliance monitoring across the data estate.")

    ds = st.session_state.datasets.copy() if "datasets" in st.session_state else pd.DataFrame()
    alerts = st.session_state.governance_alerts.copy() if "governance_alerts" in st.session_state else pd.DataFrame()
    req = st.session_state.access_requests.copy() if "access_requests" in st.session_state else pd.DataFrame()

    if ds.empty:
        st.info("No datasets available for governance monitoring yet.")
        return

    privacy_scores = pd.to_numeric(ds.get("privacy_score", pd.Series([0] * len(ds))), errors="coerce").fillna(0)
    quality_scores = pd.to_numeric(ds.get("quality_score", pd.Series([0] * len(ds))), errors="coerce").fillna(0)
    high_risk_count = int((privacy_scores >= 7).sum())
    sensitive_count = int(ds["classification"].astype(str).isin(["Confidential", "Restricted", "Highly Restricted"]).sum()) if "classification" in ds.columns else 0
    pending_review = int(ds["status"].astype(str).isin(["Submitted", "Privacy Review", "MSP Review"]).sum()) if "status" in ds.columns else 0
    avg_quality = float(quality_scores.mean()) if len(quality_scores) else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    _ = c1.metric("Total datasets", len(ds))
    _ = c2.metric("Sensitive datasets", sensitive_count)
    _ = c3.metric("High privacy risk", high_risk_count)
    _ = c4.metric("Pending governance review", pending_review)
    _ = c5.metric("Average quality", f"{avg_quality:.2f}")

    left, right = st.columns(2)
    with left:
        st.subheader("Dataset classification distribution")
        if "classification" in ds.columns:
            classification_counts = ds["classification"].astype(str).value_counts().reindex(CLASSIFICATION_LEVELS).fillna(0).astype(int)
            st.bar_chart(classification_counts)
        else:
            st.info("No classification data available.")

        st.subheader("Dataset status distribution")
        if "status" in ds.columns:
            st.bar_chart(ds["status"].astype(str).value_counts())

    with right:
        st.subheader("Purview-style label distribution")
        label_frames = []
        for report in st.session_state.get("privacy_reports", {}).values():
            if isinstance(report, pd.DataFrame) and not report.empty and "purview_style_classification" in report.columns:
                label_frames.append(report[["purview_style_classification"]].copy())
        if label_frames:
            labels = pd.concat(label_frames, ignore_index=True)
            labels = labels[labels["purview_style_classification"].astype(str).ne("None")]
            if labels.empty:
                st.info("No sensitive classification labels detected yet.")
            else:
                st.bar_chart(labels["purview_style_classification"].astype(str).value_counts())
        else:
            st.info("No privacy classification report available yet.")

        st.subheader("Access request status")
        if not req.empty and "status" in req.columns:
            st.bar_chart(req["status"].astype(str).value_counts())
        else:
            st.info("No access requests yet.")

    st.subheader("Governance risk register")
    risk_view = ds.copy()
    risk_view["privacy_score_numeric"] = privacy_scores
    risk_view["quality_score_numeric"] = quality_scores
    display_cols = [
        "dataset_name", "classification", "privacy_score_numeric", "quality_score_numeric",
        "status", "owner_tenant_id", "rows", "columns", "created_at"
    ]
    risk_view = risk_view[[c for c in display_cols if c in risk_view.columns]].copy()
    if "owner_tenant_id" in risk_view.columns:
        risk_view["provider"] = risk_view["owner_tenant_id"].apply(tenant_name)
        risk_view = risk_view.drop(columns=["owner_tenant_id"])
    st.dataframe(
        risk_view.sort_values(["privacy_score_numeric", "quality_score_numeric"], ascending=[False, True])
        if {"privacy_score_numeric", "quality_score_numeric"}.issubset(risk_view.columns) else risk_view,
        width="stretch",
        hide_index=True,
    )

    st.subheader("Governance alerts")
    if not alerts.empty:
        st.dataframe(alerts.sort_values("created_at", ascending=False), width="stretch", hide_index=True)
    else:
        st.info("No governance alerts have been generated yet. Use Governance Monitoring to run compliance checks.")


def page_privacy_review_queue():
    _ = show_header("Dataset Review / Audit",
                    "Review or audit sensitive datasets before approval or marketplace publication.")
    ds = st.session_state.datasets.copy()

    # Hide Drafts - MSP shouldn't review privacy until provider submits it
    ds = ds[ds["status"].astype(str) != "Draft"]

    ds["privacy_score_numeric"] = pd.to_numeric(ds["privacy_score"], errors="coerce")
    queue = ds[(ds["privacy_score_numeric"] >= 3) | (ds["status"].isin(["Privacy Review", "MSP Review", "Submitted"]))]
    if queue.empty:
        st.success("No datasets currently require dataset review or audit.")
        return
    for _, row in queue.iterrows():
        with st.expander(f"{row['dataset_name']} | {row['classification']} | Privacy Score {row['privacy_score']}"):
            _ = render_dataset_detail(row["dataset_id"], allow_data_preview=True)

# =============================================================================
# Data Provider pages
# =============================================================================




def page_my_datasets():
    _ = show_header("My Datasets", "Provider view is tenant-scoped. You only see datasets owned by your organization.")
    ds = visible_datasets_for_user(get_current_user())
    st.dataframe(ds, width="stretch", hide_index=True)
    if not ds.empty:
        selected = st.selectbox("Open my dataset", ds["dataset_id"].tolist(), format_func=lambda x: ds[ds["dataset_id"] == x].iloc[0]["dataset_name"])
        _ = render_dataset_detail(selected)





# =============================================================================
# Data Consumer pages
# =============================================================================


def page_marketplace():
    user = get_current_user()
    _ = show_header("Data Catalog", "Published datasets available for discovery, purchase, approval and token-based access.")
    ds = visible_datasets_for_user(user)
    if ds.empty:
        st.info("No published datasets currently available.")
        return
    c1, c2 = st.columns(2)
    with c1:
        class_filter = st.multiselect("Classification", CLASSIFICATION_LEVELS, default=[])
    with c2:
        search = st.text_input("Search")
    filtered = ds.copy()
    if class_filter:
        filtered = filtered[filtered["classification"].isin(class_filter)]
    if search:
        filtered = filtered[filtered["dataset_name"].str.lower().str.contains(search.lower()) | filtered["tags"].str.lower().str.contains(search.lower())]

    st.info(f"All published datasets are monetized. Credence/MSP retains {MSP_COMMISSION_RATE * 100:.1f}% platform commission from each approved purchase; the remaining revenue is allocated to the data provider.")

    for _, row in filtered.iterrows():
        gross = float(row["price_rm"])
        msp_fee = round(gross * MSP_COMMISSION_RATE, 2)
        provider_net = round(gross - msp_fee, 2)
        with st.expander(f"{row['dataset_name']} | {row['classification']} | RM {gross:.2f}"):
            _ = render_dataset_detail(row["dataset_id"])
            st.write(f"**Price:** RM {gross:.2f}")
            st.write(f"**Credence/MSP platform commission:** RM {msp_fee:.2f}")
            st.write(f"**Provider net revenue:** RM {provider_net:.2f}")
            purpose = st.text_area("Access purpose", value="Research, analytics, and data product evaluation.", key=f"purpose_{row['dataset_id']}")
            payment_method = st.selectbox("Payment method", PAYMENT_METHODS, key=f"pay_{row['dataset_id']}")
            if st.button("Purchase / request access", key=f"request_{row['dataset_id']}"):
                payment_status = "Successful"
                req_id = generate_id("REQ")
                requires_manual = row["classification"] in ["Confidential", "Restricted", "Highly Restricted"] or gross > 0
                status = "Pending Provider/MSP Approval" if requires_manual else "Approved"
                new_req = pd.DataFrame([{
                    "request_id": req_id,
                    "dataset_id": row["dataset_id"],
                    "dataset_name": row["dataset_name"],
                    "consumer_email": user["email"],
                    "consumer_tenant_id": user["tenant_id"],
                    "purpose": purpose,
                    "status": status,
                    "payment_status": payment_status,
                    "amount_rm": gross,
                    "msp_commission_rate": MSP_COMMISSION_RATE,
                    "msp_commission_rm": msp_fee,
                    "provider_revenue_rm": provider_net,
                    "created_at": now_str(),
                    "reviewed_by": "Auto" if status == "Approved" else "",
                    "reviewed_at": now_str() if status == "Approved" else "",
                }])
                st.session_state.access_requests = pd.concat([st.session_state.access_requests, new_req], ignore_index=True)
                _ = add_log(user["email"], f"Submitted purchase/access request {req_id} for {row['dataset_name']}", user["tenant_id"])
                if status == "Approved":
                    _ = create_token_for_request(req_id)
                st.success(f"Request submitted. Status: {status}. Payment: {payment_status} via {payment_method}.")
                st.rerun()







# =============================================================================
# MSP approval of access requests, included inside approval page when admin views
# =============================================================================

# =============================================================================
# MSP approval of access requests and catalog reference options
# =============================================================================

CONNECTION_SOURCE_PLATFORMS = [
    "Microsoft Fabric Lakehouse", "Azure Data Lake Storage", "Amazon S3", "SharePoint",
    "PostgreSQL", "Oracle", "MySQL", "Iceberg Table", "REST API", "GraphQL API",
]


def page_classification_policy_review():
    _ = ensure_enhanced_state()
    _ = show_header("Classification & Policy Review", "Review sensitivity labels, detected classifications, masking actions and assigned policies.")
    st.subheader("Current Sensitivity Labels and Policies")
    st.dataframe(st.session_state.sensitivity_catalog, width="stretch", hide_index=True)
    st.subheader("Dataset Classification Summary")
    ds = st.session_state.datasets.copy()
    if not ds.empty:
        st.dataframe(ds[["dataset_name", "domain", "classification", "privacy_score", "quality_score", "status", "tags"]], width="stretch", hide_index=True)


def get_app_base_url() -> str:
    """Return the local/demo URL used by Stripe Checkout to redirect back to Streamlit."""
    try:
        value = str(st.secrets.get("APP_BASE_URL", "")).strip()
        if value:
            return value.rstrip("/")
    except Exception:
        pass
    return "https://unified-data-catalog.streamlit.app/"


def init_stripe() -> bool:
    """Initialize Stripe using Streamlit secrets or environment variables."""
    if not STRIPE_AVAILABLE:
        st.session_state["stripe_config_status"] = "Stripe Python package is not installed."
        return False

    secret_key = ""
    try:
        secret_key = str(st.secrets.get("STRIPE_SECRET_KEY", "")).strip()
    except Exception:
        secret_key = ""

    if not secret_key:
        secret_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()

    if not secret_key:
        st.session_state["stripe_config_status"] = (
            "Stripe secret key is not configured. Add STRIPE_SECRET_KEY in .streamlit/secrets.toml."
        )
        return False

    stripe.api_key = secret_key
    st.session_state["stripe_config_status"] = "Stripe sandbox key loaded."
    return True


def get_stripe_payment_method_types() -> List[str]:
    """Read optional Stripe payment methods from secrets; default to card for widest test compatibility."""
    try:
        configured = str(st.secrets.get("STRIPE_PAYMENT_METHOD_TYPES", "")).strip()
    except Exception:
        configured = ""
    if not configured:
        return STRIPE_DEFAULT_PAYMENT_METHOD_TYPES.copy()
    methods = [m.strip().lower() for m in configured.split(",") if m.strip()]
    return methods or STRIPE_DEFAULT_PAYMENT_METHOD_TYPES.copy()


def _stripe_metadata_to_dict(session) -> Dict[str, str]:
    """Convert Stripe metadata object into a normal dictionary."""
    try:
        metadata = dict(getattr(session, "metadata", {}) or {})
    except Exception:
        metadata = {}
    return {str(k): str(v) for k, v in metadata.items()}


def _extract_dataset_name_from_stripe_session(session, metadata: Dict[str, str]) -> str:
    """Find the dataset name from Stripe metadata or expanded line item details."""
    dataset_name = metadata.get("dataset_name", "").strip()
    if dataset_name:
        return dataset_name

    try:
        line_items = getattr(session, "line_items", None)
        data = getattr(line_items, "data", []) if line_items is not None else []
        if data:
            description = str(getattr(data[0], "description", "") or "")
            if "Dataset access - " in description:
                return description.split("Dataset access - ", 1)[1].strip()
            if description:
                return description.strip()
    except Exception:
        pass

    return ""


def _resolve_current_dataset_id(dataset_id: str, dataset_name: str) -> str:
    """Resolve a dataset ID after Stripe redirect.

    Streamlit can start a fresh session after external redirect, so demo dataset IDs may
    be regenerated. This maps the old Stripe metadata back to the current in-session dataset.
    """
    datasets = st.session_state.datasets.copy()
    if datasets.empty:
        return dataset_id

    if dataset_id:
        match = datasets[datasets["dataset_id"].astype(str) == str(dataset_id)]
        if not match.empty:
            return str(match.iloc[0]["dataset_id"])

    if dataset_name:
        match = datasets[datasets["dataset_name"].astype(str).str.lower() == str(dataset_name).lower()]
        if not match.empty:
            return str(match.iloc[0]["dataset_id"])

    return dataset_id


def _retrieve_stripe_session(session_id: str):
    """Retrieve a Stripe Checkout Session with enough data to rebuild the local request after redirect."""
    if not session_id or not init_stripe():
        return None
    try:
        return stripe.checkout.Session.retrieve(
            session_id,
            expand=["line_items"],
        )
    except Exception as error:
        st.warning(f"Could not verify Stripe session online. Continuing with sandbox redirect result for demo: {error}")
        return None


def _rebuild_access_request_from_stripe(request_id: str, session_id: str):
    if not session_id:
        return None

    session = _retrieve_stripe_session(session_id)
    if session is None:
        return None

    metadata = _stripe_metadata_to_dict(session)
    stripe_status = str(getattr(session, "payment_status", ""))
    if stripe_status not in ["paid", "no_payment_required"]:
        st.warning(f"Stripe session returned payment_status={stripe_status}. Access was not granted yet.")
        return None

    dataset_name = _extract_dataset_name_from_stripe_session(session, metadata)
    old_dataset_id = metadata.get("dataset_id", "")
    dataset_id = _resolve_current_dataset_id(old_dataset_id, dataset_name)

    current_user = get_current_user() or {}
    consumer_email = metadata.get("consumer_email", "") or str(current_user.get("email", ""))
    consumer_tenant_id = metadata.get("consumer_tenant_id", "") or str(current_user.get("tenant_id", ""))
    amount = round(float(getattr(session, "amount_total", 0) or 0) / 100, 2)
    if amount <= 0:
        amount = round(float(metadata.get("amount_rm", 0) or 0), 2)

    if not dataset_name:
        dataset_row = st.session_state.datasets[st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)]
        dataset_name = str(dataset_row.iloc[0]["dataset_name"]) if not dataset_row.empty else "Unknown Dataset"

    commission = round(amount * MSP_COMMISSION_RATE, 2)
    provider_revenue = round(amount - commission, 2)

    rebuilt_request = pd.DataFrame([{
        "request_id": request_id,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "consumer_email": consumer_email,
        "consumer_tenant_id": consumer_tenant_id,
        "purpose": metadata.get("purpose", "Stripe Sandbox Checkout"),
        "status": "Approved - Pending Payment",
        "payment_status": "Stripe Checkout Created",
        "amount_rm": amount,
        "msp_commission_rate": MSP_COMMISSION_RATE,
        "msp_commission_rm": commission,
        "provider_revenue_rm": provider_revenue,
        "created_at": metadata.get("created_at", now_str()),
        "reviewed_by": metadata.get("reviewed_by", "Stripe Checkout"),
        "reviewed_at": now_str(),
        "rejection_reason": "",
        "rejected_by": "",
        "rejected_at": "",
    }])

    if st.session_state.access_requests.empty:
        st.session_state.access_requests = rebuilt_request.copy()
    else:
        st.session_state.access_requests = pd.concat([st.session_state.access_requests, rebuilt_request], ignore_index=True)

    add_log(
        consumer_email or "Stripe Checkout",
        f"Rebuilt local access request {request_id} from Stripe Checkout return for {dataset_name}",
        consumer_tenant_id or "System",
    )
    return session


def create_stripe_checkout_session(request_id: str) -> Optional[str]:
    _ = ensure_enhanced_state()
    user = get_current_user()

    idx = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_id].index
    if len(idx) == 0:
        st.error("Request not found.")
        return None

    request_row = st.session_state.access_requests.loc[idx[0]]
    if str(request_row.get("consumer_tenant_id", "")) != str(user.get("tenant_id", "")) and not is_msp_role(user["role"]):
        st.error("You can only pay for requests under your own consumer tenant.")
        return None

    amount_rm = round(_num(request_row.get("amount_rm", 0)), 2)
    if amount_rm <= 0:
        st.error("Invalid payment amount.")
        return None

    if not init_stripe():
        st.error(st.session_state.get("stripe_config_status", "Stripe is not configured."))
        return None

    base_url = get_app_base_url()
    success_url = f"{base_url}/?stripe_payment=success&request_id={request_id}&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base_url}/?stripe_payment=cancelled&request_id={request_id}"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=get_stripe_payment_method_types(),
            line_items=[{
                "price_data": {
                    "currency": "myr",
                    "product_data": {
                        "name": f"Dataset access - {request_row['dataset_name']}",
                        "description": f"Access request {request_id}",
                    },
                    "unit_amount": int(round(amount_rm * 100)),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "request_id": request_id,
                "dataset_id": str(request_row.get("dataset_id", "")),
                "dataset_name": str(request_row.get("dataset_name", "")),
                "consumer_email": str(request_row.get("consumer_email", "")),
                "consumer_tenant_id": str(request_row.get("consumer_tenant_id", "")),
                "amount_rm": str(amount_rm),
                "purpose": str(request_row.get("purpose", "")),
                "created_at": str(request_row.get("created_at", now_str())),
                "reviewed_by": str(request_row.get("reviewed_by", "")),
            },
        )
    except Exception as error:
        st.error(f"Stripe Checkout could not be created: {error}")
        return None

    st.session_state.access_requests.loc[idx, "payment_status"] = "Stripe Checkout Created"
    st.session_state.access_requests.loc[idx, "reviewed_at"] = now_str()
    add_log(user["email"], f"Created Stripe Sandbox Checkout for {request_row['dataset_name']}", user["tenant_id"])
    return session.url


def complete_stripe_payment(request_id: str, session_id: str = "") -> None:
    _ = ensure_enhanced_state()
    user = get_current_user()

    session = None
    if session_id:
        session = _retrieve_stripe_session(session_id)

    if session is not None:
        metadata = _stripe_metadata_to_dict(session)
        metadata_request_id = metadata.get("request_id", "")
        if metadata_request_id and metadata_request_id != str(request_id):
            st.error("Stripe session metadata does not match this request.")
            return
        stripe_status = str(getattr(session, "payment_status", "paid"))
        if stripe_status not in ["paid", "no_payment_required"]:
            st.warning(f"Stripe session returned payment_status={stripe_status}. Access was not granted yet.")
            return

    idx = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_id].index
    if len(idx) == 0:
        session = _rebuild_access_request_from_stripe(request_id, session_id)
        idx = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_id].index
        if len(idx) == 0:
            st.error("Stripe returned a request ID that does not exist and the request could not be rebuilt from Stripe metadata.")
            return

    request_row = st.session_state.access_requests.loc[idx[0]]
    if str(request_row.get("consumer_tenant_id", "")) != str(user.get("tenant_id", "")) and not is_msp_role(user["role"]):
        st.error("This Stripe payment does not belong to your tenant.")
        return

    already_paid = str(request_row.get("payment_status", "")) == "Paid" or str(request_row.get("status", "")) == "Access Granted"
    if already_paid:
        create_token_for_request(request_id)
        return

    stripe_reference = session_id or "STRIPE-REDIRECT"
    if session is not None:
        stripe_reference = str(getattr(session, "id", session_id))

    amount = _num(request_row.get("amount_rm", 0))
    commission = round(_num(request_row.get("msp_commission_rm", amount * MSP_COMMISSION_RATE)), 2)
    provider_rev = round(_num(request_row.get("provider_revenue_rm", amount - commission)), 2)
    tx_id = generate_id("STRIPE")

    transaction = pd.DataFrame([{
        "transaction_id": tx_id,
        "request_id": request_id,
        "dataset_id": request_row["dataset_id"],
        "dataset_name": request_row["dataset_name"],
        "consumer_email": request_row["consumer_email"],
        "payment_method": "Stripe Sandbox Checkout",
        "gateway": "Stripe Checkout Test Mode",
        "amount_rm": amount,
        "msp_commission_rm": commission,
        "provider_revenue_rm": provider_rev,
        "gateway_status": "Successful",
        "authorization_code": stripe_reference,
        "paid_at": now_str(),
    }])

    if "payment_transactions" not in st.session_state or st.session_state.payment_transactions.empty:
        st.session_state.payment_transactions = transaction.copy()
    else:
        existing_tx = st.session_state.payment_transactions[
            (st.session_state.payment_transactions["request_id"].astype(str) == str(request_id)) &
            (st.session_state.payment_transactions["gateway"].astype(str) == "Stripe Checkout Test Mode") &
            (st.session_state.payment_transactions["gateway_status"].astype(str) == "Successful")
        ]
        if existing_tx.empty:
            st.session_state.payment_transactions = pd.concat([st.session_state.payment_transactions, transaction], ignore_index=True)

    st.session_state.access_requests.loc[idx, "status"] = "Access Granted"
    st.session_state.access_requests.loc[idx, "payment_status"] = "Paid"
    st.session_state.access_requests.loc[idx, "reviewed_by"] = str(
        request_row.get("reviewed_by", "")) or "Stripe Checkout"
    st.session_state.access_requests.loc[idx, "reviewed_at"] = now_str()
    create_token_for_request(request_id)
    st.session_state.current_page = "My Tokens & Downloads"
    save_prototype_state()

    add_log(str(request_row["consumer_email"]),
            f"Completed Stripe Sandbox payment {tx_id} for {request_row['dataset_name']}",
            str(request_row.get("consumer_tenant_id", "System")))


def handle_stripe_checkout_return() -> None:
    """Handle Stripe return query parameters when the user comes back from hosted Checkout."""
    try:
        params = st.query_params
    except Exception:
        return

    stripe_payment = params.get("stripe_payment", None)
    request_id = params.get("request_id", None)
    session_id = params.get("session_id", "")

    if isinstance(stripe_payment, list):
        stripe_payment = stripe_payment[0] if stripe_payment else None
    if isinstance(request_id, list):
        request_id = request_id[0] if request_id else None
    if isinstance(session_id, list):
        session_id = session_id[0] if session_id else ""

    if stripe_payment == "success" and request_id:
        # 1. Capture the transaction details safely into memory
        st.session_state.pending_stripe_return = {
            "request_id": str(request_id),
            "session_id": str(session_id or ""),
        }
        # 2. Break the session so they must re-authenticate
        st.session_state.current_user = None

        # 3. Wipe the URL query parameters immediately so the login button works
        try:
            st.query_params.clear()
        except Exception:
            pass

        # 4. Refresh page to cleanly show the Login Screen
        st.rerun()

    elif stripe_payment == "cancelled" and request_id:
        st.warning("Stripe Checkout was cancelled. You can retry payment from this page.")
        try:
            st.query_params.clear()
        except Exception:
            pass
def complete_pending_stripe_return_after_login() -> None:
    pending = st.session_state.get("pending_stripe_return")
    if not isinstance(pending, dict):
        return

    request_id = str(pending.get("request_id", ""))
    session_id = str(pending.get("session_id", ""))
    if request_id:
        complete_stripe_payment(request_id, session_id)

    st.session_state.pending_stripe_return = None
    try:
        st.query_params.clear()
    except Exception:
        pass


def request_ready_for_payment(row: pd.Series) -> bool:
    status = str(row.get("status", ""))
    pay = str(row.get("payment_status", ""))
    return status in ["Pending Payment", "Approved - Pending Payment", "Approved"] and pay in ["Unpaid", "Pending Payment", "Pending Approval", "Stripe Checkout Created"]


def complete_simulated_payment(request_id: str, payment_method: str) -> None:
    _ = ensure_enhanced_state()
    user = get_current_user()
    idx = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_id].index
    if len(idx) == 0:
        st.error("Request not found.")
        return

    r = st.session_state.access_requests.loc[idx[0]]
    if str(r.get("consumer_email", "")) != str(user["email"]) and not is_msp_role(user["role"]):
        st.error("You can only pay for your own request.")
        return

    amount = _num(r.get("amount_rm", 0))
    commission = round(_num(r.get("msp_commission_rm", amount * MSP_COMMISSION_RATE)), 2)
    provider_rev = round(_num(r.get("provider_revenue_rm", amount - commission)), 2)
    tx_id = generate_id("PAY")
    auth_code = "AUTH-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))

    tx = pd.DataFrame([{
        "transaction_id": tx_id,
        "request_id": request_id,
        "dataset_id": r["dataset_id"],
        "dataset_name": r["dataset_name"],
        "consumer_email": r["consumer_email"],
        "payment_method": payment_method,
        "gateway": "Payment Gateway",
        "amount_rm": amount,
        "msp_commission_rm": commission,
        "provider_revenue_rm": provider_rev,
        "gateway_status": "Successful",
        "authorization_code": auth_code,
        "paid_at": now_str(),
    }])
    if "payment_transactions" not in st.session_state or st.session_state.payment_transactions.empty:
        st.session_state.payment_transactions = tx.copy()
    else:
        st.session_state.payment_transactions = pd.concat([st.session_state.payment_transactions, tx], ignore_index=True)

    st.session_state.access_requests.loc[idx, "status"] = "Access Granted"
    st.session_state.access_requests.loc[idx, "payment_status"] = "Paid"
    st.session_state.access_requests.loc[idx, "reviewed_by"] = str(r.get("reviewed_by", "")) or "Payment completed"
    st.session_state.access_requests.loc[idx, "reviewed_at"] = now_str()

    create_token_for_request(request_id)

    st.session_state.current_page = "My Tokens & Downloads"
    save_prototype_state()

    add_log(str(r["consumer_email"]),
            f"Completed simulated payment {tx_id} for {r['dataset_name']} using {payment_method}",
            str(r.get("consumer_tenant_id", "System")))
    st.success(f"Payment successful. Gateway authorization code: {auth_code}. Access token has been generated.")

def page_checkout_payment():
    _ = ensure_enhanced_state()
    user = get_current_user()
    _ = show_header("Checkout & Payment", "Review billing summary and complete payment before access is granted.")
    handle_stripe_checkout_return()

    req = st.session_state.access_requests[
        (st.session_state.access_requests["consumer_tenant_id"].astype(str) == str(user["tenant_id"])) &
        (st.session_state.access_requests["payment_status"].astype(str).isin(["Unpaid", "Pending Payment", "Stripe Checkout Created"])) &
        (st.session_state.access_requests["status"].astype(str).isin(["Pending Payment", "Approved - Pending Payment", "Approved"]))
    ].copy()

    if req.empty:
        st.info("No checkout is ready. Purchase a dataset or wait for provider/MSP approval.")
        paid = st.session_state.access_requests[
            (st.session_state.access_requests["consumer_tenant_id"].astype(str) == str(user["tenant_id"])) &
            (st.session_state.access_requests["payment_status"].astype(str) == "Paid")
        ].copy()
        if not paid.empty:
            st.subheader("Paid transactions")
            st.dataframe(paid[[c for c in ["request_id", "dataset_name", "amount_rm", "payment_status", "status", "reviewed_at"] if c in paid.columns]], width="stretch", hide_index=True)
        return

    st.dataframe(req[[c for c in ["request_id", "dataset_name", "purpose", "status", "payment_status", "amount_rm", "msp_commission_rm", "provider_revenue_rm", "created_at"] if c in req.columns]], width="stretch", hide_index=True)

    selected = st.selectbox("Select checkout item", req["request_id"].tolist(), format_func=lambda rid: f"{rid} - {req[req['request_id'] == rid].iloc[0]['dataset_name']}")
    row = req[req["request_id"] == selected].iloc[0]

    amount = _num(row.get("amount_rm", 0))
    commission = round(_num(row.get("msp_commission_rm", amount * MSP_COMMISSION_RATE)), 2)
    provider_rev = round(_num(row.get("provider_revenue_rm", amount - commission)), 2)
    service_fee = 0.00
    total = round(amount + service_fee, 2)

    st.subheader("Billing Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dataset price", f"RM {amount:,.2f}")
    c2.metric("Gateway fee", f"RM {service_fee:,.2f}")
    c3.metric("Total payable", f"RM {total:,.2f}")
    c4.metric("MSP commission", f"RM {commission:,.2f}")

    summary = pd.DataFrame([
        {"Item": "Dataset", "Description": row["dataset_name"], "Amount RM": amount},
        {"Item": "MSP platform commission", "Description": f"{MSP_COMMISSION_RATE*100:.0f}% retained by platform", "Amount RM": commission},
        {"Item": "Provider revenue", "Description": "Revenue payable to data provider", "Amount RM": provider_rev},
        {"Item": "Total payable by consumer", "Description": "Amount charged in gateway", "Amount RM": total},
    ])
    st.dataframe(summary, width="stretch", hide_index=True)

    st.subheader("Payment Mode")
    payment_mode = st.radio("Choose payment mode", PAYMENT_MODES, horizontal=True)

    if payment_mode == "Simulated Gateway":
        st.caption("Offline prototype mode. This keeps the demo working without external payment services.")
        method = st.radio("Choose simulated payment method", PAYMENT_METHODS, horizontal=True)
        with st.expander("Simulated payment gateway details", expanded=True):
            if method == "Credit / Debit Card":
                st.text_input("Cardholder name", value="Demo User")
                st.text_input("Card number", value="4111 1111 1111 1111")
                st.text_input("Expiry", value="12/28")
                st.text_input("CVV", value="123", type="password")
            elif method == "Online Banking / FPX":
                st.selectbox("Bank", ["Maybank2u", "CIMB Bank", "Public Bank", "RHB Bank", "Hong Leong Bank", "Bank Islam", "BSN", "AmBank", "Bank Rakyat"])
            elif "eWallet" in method or method in ["GrabPay", "Boost"]:
                st.text_input("Wallet mobile number", value="+60123456789")

        agree = st.checkbox("I confirm this payment and understand access will be token-controlled.", key=f"simulated_agree_{selected}")
        if st.button("Pay Now with Simulated Gateway", type="primary", disabled=not agree, key=f"simulated_pay_{selected}"):
            complete_simulated_payment(selected, method)
            st.rerun()

    else:
        st.caption("Stripe Test Mode redirects the consumer to a hosted checkout page. No real money is charged when using Stripe test keys.")

        agree = st.checkbox("I confirm this Stripe sandbox checkout and understand access is granted only after successful return.", key=f"stripe_agree_{selected}")
        if st.button("Create Stripe Checkout Session", type="primary", disabled=not agree, key=f"stripe_checkout_{selected}"):
            checkout_url = create_stripe_checkout_session(selected)
            if checkout_url:
                st.success("Stripe Checkout session created.")
                st.link_button("Open Stripe Hosted Checkout", checkout_url)
                st.info("After completing Stripe test payment, you will be redirected back here and the access token will be generated.")


def page_my_access_requests():
    _ = ensure_enhanced_state()
    user = get_current_user()
    _ = show_header("My Access Requests", "Track dataset request, approval and payment status.")
    req = st.session_state.access_requests[st.session_state.access_requests["consumer_tenant_id"].astype(str) == str(user["tenant_id"])].copy()
    if req.empty:
        st.info("No access requests yet.")
        return
    safe_cols = ["request_id", "dataset_name", "purpose", "status", "payment_status", "amount_rm", "msp_commission_rm", "provider_revenue_rm", "approval_workflow", "rejection_reason", "created_at", "reviewed_by", "reviewed_at"]
    st.dataframe(req[[c for c in safe_cols if c in req.columns]], width="stretch", hide_index=True)
    pending_payment = req[req.apply(request_ready_for_payment, axis=1)] if not req.empty else pd.DataFrame()
    if not pending_payment.empty:
        st.info("You have approved checkout items. Open Checkout & Payment to complete the payment and generate access tokens.")

TAG_OPTIONS = [
    # Business domain
    "Customer", "Billing", "Service", "Network", "Finance", "Operations",
    "Sales & Marketing", "Product", "Digital Services", "Customer Experience",
    "Enterprise Services",

    # Use case
    "Customer Segmentation", "Revenue Analysis", "Payment Behaviour Analysis",
    "Network Performance Analysis", "Service Assurance", "Churn Analysis",
    "Forecasting", "Business Intelligence", "Dashboarding", "Academic Research",
    "Market Analysis", "Operational Reporting",

    # Geography
    "Malaysia", "Peninsular Malaysia", "Sabah", "Sarawak", "Kuala Lumpur",
    "Selangor", "Penang", "Johor",

    # Industry
    "Telecommunications", "Banking", "Insurance", "Healthcare", "Education",
    "Government", "Retail", "Manufacturing", "Transportation", "Energy",
]

DOMAIN_OPTIONS = [
    "Customer", "Billing", "Service", "Network", "Operations", "Finance",
    "Sales & Marketing", "Product", "Digital Services", "Customer Experience",
    "Risk & Compliance", "Research", "Geospatial", "IoT", "Enterprise Services",
    "Mobile", "Broadband", "Telecommunications", "Education", "Healthcare",
    "Government", "Banking", "Insurance", "Retail", "Manufacturing",
    "Transportation", "Energy", "Smart City", "Agriculture", "Cybersecurity",
    "Human Resources", "Procurement", "Supply Chain", "Environmental",
    "Public Sector", "Open Data", "Other",
]

ASSET_TYPE_OPTIONS = [
    "CSV", "Excel", "Parquet", "JSON", "Delta", "Iceberg", "SQL Table",
    "Database View", "API", "REST API", "GraphQL API", "Kafka Stream",
    "Event Stream", "Power BI Dataset", "Fabric Lakehouse Table", "Fabric Shortcut",
    "SharePoint File", "S3 Object", "ADLS File", "TXT", "XML", "Avro", "ORC",
    "YAML", "PDF", "Image", "Video", "Notebook", "Lakehouse Files",
    "Delta Table", "Warehouse Table", "Dataverse Table", "Snowflake Table",
    "BigQuery Table", "PostgreSQL Table", "Oracle Table", "MySQL Table",
    "MongoDB Collection", "Unknown",
]

CATALOG_TITLES = {
    "customer.csv": "Telecommunication Customer Profile Dataset",
    "billing.csv": "Telecommunication Billing and Payment Dataset",
    "service.csv": "Telecommunication Service and Network Performance Dataset",
}

CATALOG_DESCRIPTIONS = {
    "customer.csv": "Synthetic telecommunication customer profile dataset representing individual and business subscribers. It includes customer type, location, subscription plan, billing preference, demographic attributes, KYC status, and direct identifiers used for customer segmentation and customer behavior analysis.",
    "billing.csv": "Synthetic telecommunication billing dataset containing invoice, customer, service, billing period, pricing tier, currency, subtotal, discount, tax, total amount, and payment method information. It supports revenue analysis, payment behavior review, and billing performance analysis.",
    "service.csv": "Synthetic telecommunication service and network performance dataset describing service subscriptions, service status, region, access technology, router model, SLA tier, bandwidth, monthly usage, latency, jitter, and outage counts. It supports service quality, network operations, and customer experience analysis.",
}

CATALOG_TAGS = {
    "customer.csv": "Customer, Telecommunications, Customer Segmentation, Academic Research, Malaysia",
    "billing.csv": "Billing, Telecommunications, Revenue Analysis, Payment Behaviour Analysis, Finance, Malaysia",
    "service.csv": "Service, Network, Telecommunications, Network Performance Analysis, Service Assurance, Malaysia",
}

CATALOG_DOMAINS = {"customer.csv": "Customer", "billing.csv": "Billing", "service.csv": "Service"}

PROVIDER_USAGE_TERMS = [
    "I confirm that I am authorized to register this dataset for catalog publication.",
    "I confirm that the dataset location, description, pricing, business tags and ownership details are accurate.",
    "I understand that detected sensitive data may require masking, governance review and approval before publication.",
    "I agree that the platform records audit activity and applies the configured MSP commission for approved purchases.",
]

CONSUMER_USAGE_TERMS = [
    "The dataset must only be used for the approved purpose stated in the access request.",
    "Masked or anonymized data must not be reverse engineered or re-identified.",
    "The dataset must not be redistributed, resold, or published without provider approval.",
    "Access tokens, download links and usage activity are logged and may be revoked if policy is violated.",
]

ACCESS_PURPOSE_OPTIONS = [
    "Academic research", "Teaching and learning", "Business intelligence dashboard",
    "Customer segmentation", "Churn analysis", "Revenue analysis",
    "Network performance analysis", "Machine learning model development",
    "Data product evaluation", "Other",
]

BI_TOOL_IDEAS = [
    "Create dashboards using Power BI, Tableau, Apache Superset, or other BI tools to discover patterns and trends.",
    "Join multiple datasets to perform more comprehensive cross-domain analysis.",
    "Build machine learning models to forecast future trends, demand, revenue, or customer behaviour.",
    "Explore dataset insights to support better business decision-making.",
]


def apply_catalog_css():
    st.markdown("""
    <style>
    .catalog-card {background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;margin:12px 0;box-shadow:0 2px 10px rgba(15,23,42,0.05);}
    .catalog-title {font-size:19px;font-weight:780;color:#111827;margin-bottom:6px;}
    .catalog-meta {font-size:13px;color:#475569;margin-bottom:8px;}
    .catalog-desc {font-size:14px;color:#334155;line-height:1.45;margin-top:8px;margin-bottom:10px;}
    .tag-pill {display:inline-block;padding:4px 9px;border-radius:999px;background:#eef2ff;color:#1d4ed8;font-size:12px;font-weight:650;margin:2px 4px 2px 0;border:1px solid #dbeafe;}
    .soft-panel {background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;padding:16px;margin:10px 0;}
    .section-note {color:#64748b;font-size:13px;margin-bottom:8px;}
    </style>
    """, unsafe_allow_html=True)


def tag_pills(tags: str) -> str:
    parts = [t.strip() for t in str(tags or "").split(",") if t.strip()]
    return " ".join([f"<span class='tag-pill'>{t}</span>" for t in parts[:8]])


def clean_label_list(values: List[str]) -> List[str]:
    return list(dict.fromkeys([str(value).strip() for value in values if str(value).strip()]))


def get_available_domains(include_other: bool = True) -> List[str]:
    domains = clean_label_list(list(st.session_state.get("business_domains", [])) + DOMAIN_OPTIONS)
    if include_other and "Other" not in domains:
        domains.append("Other")
    if not include_other:
        domains = [domain for domain in domains if domain != "Other"]
    return domains


def add_business_domain(domain_name: str) -> Optional[str]:
    cleaned = str(domain_name or "").strip()
    if not cleaned:
        return None
    st.session_state.business_domains = clean_label_list(get_available_domains(include_other=True) + [cleaned])
    return cleaned


def catalog_title(row) -> str:
    return str(row.get("catalog_title", "") or CATALOG_TITLES.get(str(row.get("dataset_name", "")), row.get("dataset_name", "Untitled Dataset")))








def dataset_visibility_mode(row, user: Dict) -> str:
    if is_provider_role(user["role"]) and row["owner_tenant_id"] == user["tenant_id"]:
        return "full"
    if is_msp_role(user["role"]):
        return "governance"
    if is_consumer_role(user["role"]) and user_has_dataset_access(row["dataset_id"], user):
        return "full"
    return "public"


def draw_lineage_for_dataset(dataset_name):
    dot = f"""
    digraph G {{

        rankdir=LR;
        bgcolor="transparent";
        splines=ortho;
        nodesep=0.7;
        ranksep=1.0;

        node [
            shape=box
            style="rounded,filled"
            fontname="Segoe UI"
            fontsize=11
            margin="0.2,0.1"
        ];

        source [
            label="Source Platform\\n(Fabric / S3 / Database)"
            fillcolor="#dbeafe"
        ];

        dataset [
            label="{dataset_name}"
            fillcolor="#e0f2fe"
        ];

        metadata [
            label="Metadata Discovery"
            fillcolor="#dcfce7"
        ];

        privacy [
            label="PII Detection\\nClassification\\nMasking"
            fillcolor="#fef3c7"
        ];

        quality [
            label="Quality Assessment"
            fillcolor="#fce7f3"
        ];

        catalog [
            label="Unified Data Catalog"
            fillcolor="#ede9fe"
        ];

        access [
            label="Access Request"
            fillcolor="#fee2e2"
        ];

        token [
            label="Access Token"
            fillcolor="#fef9c3"
        ];

        usage [
            label="Analytics & Research"
            fillcolor="#ccfbf1"
        ];

        source -> dataset;
        dataset -> metadata;
        metadata -> privacy;
        privacy -> quality;
        quality -> catalog;
        catalog -> access;
        access -> token;
        token -> usage;
    }}
    """
    st.graphviz_chart(dot)


def processing_dataset_key(dataset_name: str) -> str:
    """Return the dataset_name value used inside the Fabric-generated report CSVs."""
    return str(dataset_name).strip().lower().replace(".csv", "")


def dataset_masked_output_file(dataset_name: str) -> str:
    key = processing_dataset_key(dataset_name)
    return DEMO_MASKED_DATASET_FILES.get(f"{key}.csv", "")


def output_file_display_path(filename: str) -> str:
    if not filename:
        return ""
    path = find_project_file(filename)
    return path if path else filename


def render_output_table(title: str, filename: str, df: pd.DataFrame, download_name: Optional[str] = None, key: Optional[str] = None) -> None:
    st.subheader(title)
    if isinstance(df, pd.DataFrame) and not df.empty:
        st.dataframe(df, width="stretch", hide_index=True)
        dataframe_download_button(df, f"Download {download_name or filename}", download_name or filename, key=key)
    else:
        st.info("No matching records found for this dataset. Upload or connect a dataset and run processing to generate this report dynamically.")

def get_processing_output_for_dataset(dataset_id: str, report_key: str, dataset_name: str = "") -> pd.DataFrame:

    outputs = st.session_state.get("processing_outputs", {})
    if isinstance(outputs, dict):
        dataset_outputs = outputs.get(dataset_id, {})
        if isinstance(dataset_outputs, dict):
            df = dataset_outputs.get(report_key, pd.DataFrame())
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df.copy()

    # Backward-compatible fallback for demo files generated by the Fabric notebook.
    if dataset_name:
        return get_report_for_dataset(report_key, dataset_name)
    return pd.DataFrame()


def render_dataset_quality_outputs(dataset_id: str, dataset_name: str) -> None:
    dataset_key = processing_dataset_key(dataset_name)
    df_scores = get_processing_output_for_dataset(dataset_id, "dataset_quality_scores", dataset_name)
    render_output_table(
        "Dataset quality scores",
        PROCESSING_REPORT_FILES["dataset_quality_scores"],
        df_scores,
        f"{dataset_key}_dataset_quality_scores.csv",
        key=f"dl_qs_{dataset_id}"
    )
    df_column = get_processing_output_for_dataset(dataset_id, "column_level_quality", dataset_name)
    render_output_table(
        "Column-level quality report",
        PROCESSING_REPORT_FILES["column_level_quality"],
        df_column,
        f"{dataset_key}_column_level_quality_report.csv",
        key=f"dl_col_{dataset_id}"
    )


def render_privacy_masking_policy_output(dataset_id: str, dataset_name: str) -> None:
    dataset_key = processing_dataset_key(dataset_name)
    df = get_processing_output_for_dataset(dataset_id, "privacy_masking_policy", dataset_name)
    render_output_table(
        "Privacy and masking policy report",
        PROCESSING_REPORT_FILES["privacy_masking_policy"],
        df,
        f"{dataset_key}_privacy_and_masking_policy_report.csv",
        key=f"dl_priv_{dataset_id}"
    )

def render_processing_summary_outputs(dataset_id: str, dataset_name: str) -> None:
    dataset_key = processing_dataset_key(dataset_name)
    df = get_processing_output_for_dataset(dataset_id, "processing_summary", dataset_name)
    st.subheader("Processing summary overview")
    if isinstance(df, pd.DataFrame) and not df.empty:
        overview_df = df.head(1).copy()
        st.dataframe(overview_df, width="stretch", hide_index=True)
        dataframe_download_button(df, "Download processing summary report", f"{dataset_key}_processing_summary_report.csv", key=f"dl_sum_{dataset_id}")
    else:
        st.info("No processing summary is available yet. Upload a file or connect a source with readable data and run processing.")

def render_governance_action_panel(dataset_id: str) -> None:
    user = get_current_user()
    ds = st.session_state.datasets[
        st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)
    ]

    if ds.empty:
        st.error("Dataset not found.")
        return

    row = ds.iloc[0]

    st.subheader("Dataset review action")

    recommendation = create_policy_summary(
        row.get("classification", "Internal"),
        row.get("privacy_score", 0),
        row.get("is_paid", True)
    )

    st.write("**Recommended governance controls**")
    st.json(recommendation)

    c1, c2, c3 = st.columns(3)

    if c1.button("Approve & Publish Dataset", key=f"detail_approve_{dataset_id}"):
        idx = st.session_state.datasets[
            st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)
        ].index

        st.session_state.datasets.loc[idx, "status"] = "Published"
        st.session_state.datasets.loc[idx, "approved_by"] = user["email"]
        st.session_state.datasets.loc[idx, "approved_at"] = today_str()

        add_log(
            user["email"],
            f"Approved and published dataset {row['dataset_name']}",
            user["tenant_id"]
        )

        st.rerun()

    rejection_reason = c3.text_area(
        "Reason for rejection",
        key=f"detail_dataset_rejection_reason_{dataset_id}",
        placeholder="Explain why this dataset is rejected.",
    )

    if c3.button("Reject dataset", key=f"detail_reject_{dataset_id}"):
        if not rejection_reason.strip():
            st.warning("Please provide a rejection reason before rejecting this dataset.")
        else:
            idx = st.session_state.datasets[
                st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)
            ].index

            st.session_state.datasets.loc[idx, "status"] = "Rejected"
            st.session_state.datasets.loc[idx, "rejection_reason"] = rejection_reason.strip()
            st.session_state.datasets.loc[idx, "rejected_by"] = user["email"]
            st.session_state.datasets.loc[idx, "rejected_at"] = now_str()

            add_log(
                user["email"],
                f"Rejected dataset {row['dataset_name']}: {rejection_reason.strip()}",
                user["tenant_id"]
            )

            st.rerun()

    st.divider()

    st.subheader("Post-publication governance action")
    st.caption(
        "Use this if a published dataset is later found to violate privacy, metadata, licensing, or compliance requirements."
    )

    suspension_reason = st.text_area(
        "Suspension reason",
        key=f"detail_dataset_suspension_reason_{dataset_id}",
        placeholder="Example: Privacy violation detected after publication, incorrect masking, expired license, or policy breach.",
    )

    s1, s2 = st.columns(2)

    with s1:
        if str(row.get("status", "")) == "Published":
            if st.button("Suspend / Hide Dataset", key=f"detail_suspend_{dataset_id}"):
                if not suspension_reason.strip():
                    st.warning("Please provide a suspension reason before suspending this dataset.")
                else:
                    idx = st.session_state.datasets[
                        st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)
                    ].index

                    st.session_state.datasets.loc[idx, "status"] = "Suspended"
                    st.session_state.datasets.loc[idx, "suspension_reason"] = suspension_reason.strip()
                    st.session_state.datasets.loc[idx, "suspended_by"] = user["email"]
                    st.session_state.datasets.loc[idx, "suspended_at"] = now_str()

                    if (
                        "tokens" in st.session_state
                        and isinstance(st.session_state.tokens, pd.DataFrame)
                        and not st.session_state.tokens.empty
                        and "dataset_id" in st.session_state.tokens.columns
                    ):
                        token_idx = st.session_state.tokens[
                            st.session_state.tokens["dataset_id"].astype(str) == str(dataset_id)
                        ].index

                        if len(token_idx):
                            st.session_state.tokens.loc[token_idx, "status"] = "Revoked"

                    add_log(
                        user["email"],
                        f"Suspended dataset {row['dataset_name']}: {suspension_reason.strip()}",
                        user["tenant_id"]
                    )

                    st.success("Dataset suspended. It is now hidden from consumers and related tokens are revoked.")
                    st.rerun()
        else:
            st.info("Suspend action is available only when the dataset status is Published.")

    with s2:
        if str(row.get("status", "")) == "Suspended":
            if st.button("Restore Dataset", key=f"detail_restore_{dataset_id}"):
                idx = st.session_state.datasets[
                    st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)
                ].index

                st.session_state.datasets.loc[idx, "status"] = "Published"

                add_log(
                    user["email"],
                    f"Restored dataset {row['dataset_name']}",
                    user["tenant_id"]
                )

                st.success("Dataset restored and visible to consumers again.")
                st.rerun()
        else:
            st.info("Restore action is available only when the dataset status is Suspended.")

    if str(row.get("status", "")) == "Suspended":
        if str(row.get("suspension_reason", "")).strip():
            st.warning(f"Current suspension reason: {row.get('suspension_reason', '')}")
        if str(row.get("suspended_by", "")).strip():
            st.caption(
                f"Suspended by {row.get('suspended_by', '')} at {row.get('suspended_at', '')}"
            )

    st.divider()

    st.subheader("Access requests linked to this dataset")

    req = (
        st.session_state.access_requests.copy()
        if "access_requests" in st.session_state
        else pd.DataFrame()
    )

    if isinstance(req, pd.DataFrame) and not req.empty and "dataset_id" in req.columns:
        req = req[req["dataset_id"].astype(str) == str(dataset_id)].copy()

    if isinstance(req, pd.DataFrame) and not req.empty:
        safe_cols = [
            c for c in [
                "request_id",
                "consumer_email",
                "purpose",
                "status",
                "payment_status",
                "amount_rm",
                "msp_commission_rm",
                "provider_revenue_rm",
                "created_at",
                "reviewed_by",
                "reviewed_at"
            ]
            if c in req.columns
        ]

        st.dataframe(req[safe_cols], width="stretch", hide_index=True)
    else:
        st.info("No access requests are linked to this dataset yet.")


def render_dataset_detail(dataset_id: str, allow_data_preview: bool = False, public_view: bool = False) -> None:
    _ = ensure_enhanced_state()
    user = get_current_user()
    ds = st.session_state.datasets[st.session_state.datasets["dataset_id"] == dataset_id]
    if ds.empty:
        st.error("Dataset not found.")
        return
    row = ds.iloc[0]
    mode = "public" if public_view else dataset_visibility_mode(row, user)
    is_owner_provider = bool(user and is_provider_role(user["role"]) and str(row.get("owner_tenant_id", "")) == str(
        user.get("tenant_id", "")))

    st.markdown(f"<div class='catalog-title'>{catalog_title(row)}</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='catalog-meta'>Provider: {tenant_name(row['owner_tenant_id'])} · Domain: {row.get('domain', 'Other')} · {row.get('asset_type', row.get('format', 'Unknown'))} · {int(row.get('rows', 0)):,} rows · {int(row.get('columns', 0))} columns · RM {float(row.get('price_rm', 0)):.2f}</div>",
        unsafe_allow_html=True)
    st.markdown(f"<div class='catalog-desc'>{row.get('description', '')}</div>", unsafe_allow_html=True)
    st.markdown(tag_pills(row.get("tags", "")), unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    _ = c1.metric("Quality", f"{float(row.get('quality_score', 0)):.2f}%")
    _ = c2.metric("Status", row.get("status", ""))
    _ = c3.metric("Downloads", int(row.get("download_count", 0)))

    if str(row.get("status", "")) == "Rejected" and str(row.get("rejection_reason", "")).strip():
        st.error(f"Rejection reason: {row.get('rejection_reason', '')}")

    if is_owner_provider and str(row.get("status", "")) in ["Draft", "Rejected"]:
        st.info(
            "This dataset is currently a Draft (or Rejected) and is not published to the catalog. Review the processing outputs below before submitting.")

        if can_approve_provider_request(user["role"]):
            approval_req = get_provider_setting(user["tenant_id"])
            btn_label = "Submit Publication Request" if approval_req else "Publish Dataset directly (MSP approval disabled)"

            # --- MODIFIED: Added side-by-side layout for Delete and Submit buttons ---
            action_col1, action_col2 = st.columns([1, 4])

            with action_col1:
                if st.button("🗑️ Delete Draft", type="secondary", key=f"delete_draft_{dataset_id}"):
                    # Deep clean: Remove from main dataframe and all related storage dictionaries
                    st.session_state.datasets = st.session_state.datasets[
                        st.session_state.datasets["dataset_id"] != dataset_id].reset_index(drop=True)
                    st.session_state.metadata_store.pop(dataset_id, None)
                    st.session_state.data_store.pop(dataset_id, None)
                    st.session_state.quality_reports.pop(dataset_id, None)
                    st.session_state.privacy_reports.pop(dataset_id, None)
                    if "processing_outputs" in st.session_state and isinstance(st.session_state.processing_outputs,
                                                                               dict):
                        st.session_state.processing_outputs.pop(dataset_id, None)

                    _ = add_log(user["email"], f"Deleted draft dataset {row.get('dataset_name', '')}",
                                user["tenant_id"])
                    st.success("Draft deleted successfully.")
                    st.rerun()

            with action_col2:
                if st.button(btn_label, type="primary", key=f"submit_pub_{dataset_id}"):
                    idx = st.session_state.datasets[st.session_state.datasets["dataset_id"] == dataset_id].index
                    if approval_req:
                        st.session_state.datasets.loc[idx, "status"] = "MSP Review"
                        _ = add_log(user["email"], f"Submitted dataset {row.get('dataset_name', '')} for MSP review",
                                    user["tenant_id"])
                        st.success("Submitted for MSP Review. It will appear in the catalog once approved.")
                    else:
                        st.session_state.datasets.loc[idx, "status"] = "Published"
                        st.session_state.datasets.loc[idx, "approved_by"] = user["email"]
                        st.session_state.datasets.loc[idx, "approved_at"] = today_str()
                        _ = add_log(user["email"], f"Published dataset {row.get('dataset_name', '')} directly",
                                    user["tenant_id"])
                        st.success("Dataset is now published to the catalog.")
                    st.rerun()
            # --- END MODIFIED BLOCK ---

        else:
            st.warning(
                f"Your current role ({user['role']}) allows you to review this draft and maintain metadata, but only a Provider Administrator or Data Owner can submit or delete it.")

    elif is_owner_provider and str(row.get("status", "")) in ["Submitted", "MSP Review", "Privacy Review"]:
        st.info("This dataset is currently pending MSP review. It is not yet visible to consumers.")

    st.write(f"**Source platform:** {row.get('source_platform', '')}")
    policy_version = row.get("usage_policy_version", "v1.0")

    if pd.isna(policy_version) or str(policy_version).strip().lower() in ["", "nan", "none", "null"]:
        policy_version = "v1.0"

    st.write(
        f"**Classification:** {row.get('classification', '')} | "
        f"**Privacy risk:** {row.get('privacy_score', '')} / 10 | "
        f"**Policy version:** {policy_version}"
    )

    if str(row.get("storage_platform", "")).strip():
        with st.expander("Storage reference"):
            st.write(
                "The platform stores the catalog and governance reference. The physical data remains in the external platform, such as Microsoft Fabric, ADLS or S3.")
            st.write(f"**Storage platform:** {row.get('storage_platform', '')}")
            st.write(f"**Workspace:** {row.get('fabric_workspace', '')}")
            st.write(f"**Lakehouse:** {row.get('lakehouse_name', '')}")
            st.code(str(row.get("fabric_path", "")), language="text")
            if str(row.get("fabric_url", "")).startswith("https://"):
                st.link_button("Open storage location", row.get("fabric_url"))

    tab_labels = ["Metadata", "Dataset to be Monetized", "Quality", "Privacy & Masking", "Processing Summary",
                  "Lineage"]
    if user and can_review_dataset(user.get("role", "")):
        tab_labels.append("Governance Action")
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        safe_meta = st.session_state.metadata_store.get(dataset_id, {}).copy()
        if mode == "governance":
            _ = safe_meta.pop("OneLake URL", None)
            _ = safe_meta.pop("ABFSS Path", None)
        st.subheader("Metadata table")
        metadata_rows = []
        for key, value in safe_meta.items():
            if isinstance(value, (dict, list)):
                display_value = json.dumps(value, ensure_ascii=False)
            else:
                display_value = str(value)
            metadata_rows.append({"Metadata field": key, "Value": display_value})
        if metadata_rows:
            st.dataframe(pd.DataFrame(metadata_rows), width="stretch", hide_index=True)
        else:
            st.info("No metadata available for this dataset.")
        with st.expander("Raw metadata JSON"):
            st.json(safe_meta)

    with tabs[1]:
        st.subheader("Final dataset for monetization / consumer view")
        st.caption(
            "This is the governed dataset view that consumers receive after approval, payment and token generation.")
        store = st.session_state.data_store.get(dataset_id, {})
        consumer_view = store.get("authorized") if isinstance(store.get("authorized"), pd.DataFrame) else store.get(
            "masked")
        if isinstance(consumer_view, pd.DataFrame) and not consumer_view.empty:
            st.dataframe(consumer_view.head(50), width="stretch", hide_index=True)
            _ = dataframe_download_button(consumer_view, "Download consumer-view dataset",
                                          f"consumer_view_{row['dataset_name']}", key=f"dl_cons_{dataset_id}")
        else:
            st.info("No consumer-view dataset is available yet.")
        if is_owner_provider:
            raw_df = store.get("cleaned")
            if isinstance(raw_df, pd.DataFrame) and not raw_df.empty:
                with st.expander("Provider-only raw / cleaned source preview"):
                    st.caption(
                        "This preview is shown only to the owning provider for verification. Consumers do not see this raw view.")
                    st.dataframe(raw_df.head(50), width="stretch", hide_index=True)

    with tabs[2]:
        render_dataset_quality_outputs(dataset_id, row["dataset_name"])

    with tabs[3]:
        render_privacy_masking_policy_output(dataset_id, row["dataset_name"])

    with tabs[4]:
        render_processing_summary_outputs(dataset_id, row["dataset_name"])

    with tabs[5]:
        _ = draw_lineage_flow(row.get("dataset_name", "Dataset"))

    if len(tabs) > 6:
        with tabs[6]:
            render_governance_action_panel(dataset_id)

def filter_catalog_datasets():
    user = get_current_user()
    ds = st.session_state.datasets.copy()
    if not is_msp_role(user["role"]):
        ds = ds[ds["status"] == "Published"] if not is_provider_role(user["role"]) else ds[(ds["status"] == "Published") | (ds["owner_tenant_id"] == user["tenant_id"])]
    return ds


def render_purchase_form(row):
    user = get_current_user()
    with st.expander("Access request and policy acceptance", expanded=True):
        purpose_choice = st.selectbox("Access purpose", ACCESS_PURPOSE_OPTIONS, key=f"purpose_choice_{row['dataset_id']}")
        other_purpose = ""
        if purpose_choice == "Other":
            other_purpose = st.text_area("Custom access purpose", help="Provide additional details for provider and MSP review.", height=120, max_chars=500)
        st.write("**Data usage policy**")
        for term in CONSUMER_USAGE_TERMS: st.write(f"• {term}")
        payment_method = st.selectbox("Payment method", PAYMENT_METHODS, key=f"pay_{row['dataset_id']}")
        accepted = st.checkbox("I accept the data usage policy terms.", key=f"accept_{row['dataset_id']}")
        if st.button("Submit access request", key=f"submit_req_{row['dataset_id']}"):
            purpose = other_purpose.strip() if purpose_choice == "Other" else purpose_choice
            if not purpose: st.error("Please provide an access purpose."); return
            if not accepted: st.error("Please accept the usage policy first."); return
            gross = float(row.get("price_rm", 0)); msp_fee = round(gross * MSP_COMMISSION_RATE, 2); provider_net = round(gross - msp_fee, 2)
            req_id = generate_id("REQ")
            status = "Pending Provider/MSP Approval" if row.get("classification") in ["Confidential", "Restricted", "Highly Restricted"] or gross > 0 else "Approved"
            new_req = pd.DataFrame([{"request_id": req_id, "dataset_id": row["dataset_id"], "dataset_name": row["dataset_name"], "consumer_email": user["email"], "consumer_tenant_id": user["tenant_id"], "purpose": purpose, "status": status, "payment_status": "Successful", "amount_rm": gross, "msp_commission_rate": MSP_COMMISSION_RATE, "msp_commission_rm": msp_fee, "provider_revenue_rm": provider_net, "created_at": now_str(), "reviewed_by": "Auto" if status == "Approved" else "", "reviewed_at": now_str() if status == "Approved" else "", "accepted_policy": True}])
            st.session_state.access_requests = pd.concat([st.session_state.access_requests, new_req], ignore_index=True)
            _ = add_log(user["email"], f"Submitted access request {req_id} for {row['dataset_name']}", user["tenant_id"])
            if status == "Approved": _ = create_token_for_request(req_id)
            st.success(f"Request submitted. Status: {status}. Payment method: {payment_method}.")
            st.session_state.quick_request_dataset = None
            st.rerun()


def render_catalog_cards(filtered: pd.DataFrame):
    user = get_current_user()
    for _, row in filtered.iterrows():
        mode = dataset_visibility_mode(row, user)
        st.markdown("<div class='catalog-card'>", unsafe_allow_html=True)
        st.markdown(f"<div class='catalog-title'>{catalog_title(row)}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='catalog-meta'>{tenant_name(row['owner_tenant_id'])} · {row.get('domain','Other')} · {row.get('asset_type', row.get('format','Unknown'))} · {int(row.get('rows',0)):,} rows · {int(row.get('columns',0))} columns · RM {float(row.get('price_rm',0)):.2f}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='catalog-desc'>{row.get('description','')}</div>", unsafe_allow_html=True)
        st.markdown(tag_pills(row.get("tags", "")), unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns([1,1,1,1.4])
        _ = c1.metric("Quality", f"{float(row.get('quality_score', 0)):.2f}%"); _ = c2.metric("Downloads", int(row.get("download_count", 0))); _ = c3.metric("Status", row.get("status", ""))
        with c4:
            if st.button("View details", key=f"view_{row['dataset_id']}"):
                st.session_state.selected_catalog_dataset = row["dataset_id"]
            if is_consumer_role(user["role"]) and not user_has_dataset_access(row["dataset_id"], user):
                if st.button("Purchase / request", key=f"quick_buy_{row['dataset_id']}"):
                    st.session_state.quick_request_dataset = row["dataset_id"]
        st.markdown("</div>", unsafe_allow_html=True)
        if st.session_state.get("selected_catalog_dataset") == row["dataset_id"]:
            with st.expander("Dataset details", expanded=True):
                _ = render_dataset_detail(row["dataset_id"], allow_data_preview=(mode == "full"), public_view=(mode == "public"))
        if st.session_state.get("quick_request_dataset") == row["dataset_id"] and is_consumer_role(user["role"]):
            _ = render_purchase_form(row)




def page_global_catalog():
    _ = page_data_catalog()








def page_consumer_dashboard():
    _ = ensure_enhanced_state(); user = get_current_user()
    _ = show_header("Consumer Dashboard", "PSM access overview and recommended next steps.")
    req = st.session_state.access_requests[st.session_state.access_requests["consumer_email"] == user["email"]]; tok = st.session_state.tokens[st.session_state.tokens["consumer_tenant_id"].astype(str) == str(user["tenant_id"])]
    c1, c2, c3, c4 = st.columns(4)
    _ = c1.metric("My requests", len(req)); _ = c2.metric("Approved tokens", int((tok["status"] == "Active").sum()) if not tok.empty else 0); _ = c3.metric("Available catalog assets", int((st.session_state.datasets["status"] == "Published").sum())); _ = c4.metric("Total spend RM", f"{float(pd.to_numeric(req.get('amount_rm', pd.Series(dtype=float)), errors='coerce').sum() if not req.empty else 0):,.2f}")
    st.subheader("Recommended workflow")
    for i, text in enumerate(["Browse the Data Catalog using title, provider, domain, tag, type and size filters.", "Review public metadata and submit an access purpose with policy acceptance.", "Review the billing summary, choose a payment method, simulate gateway payment, then use the issued token to download the authorized masked dataset or open BI tools."], 1):
        st.markdown(f"<div class='flow-box'>{i}. {text}</div>", unsafe_allow_html=True)










def page_user_guide():
    _ = ensure_enhanced_state(); user = get_current_user(); _ = show_header("User Guide", "Role-based process guide for the prototype platform.")
    st.subheader("Platform concept"); st.write("The platform is a governed catalog and monetization portal. It stores metadata, policies, access requests and tokens, while the physical datasets remain in external platforms such as Microsoft Fabric, ADLS, S3, databases or APIs.")
    if is_msp_role(user["role"]): steps = ["Monitor dashboard KPIs.", "Review datasets in Data Catalog and Dataset Approval Queue.", "Configure sensitivity labels and policies.", "Provision tenants, users and Fabric workspace references.", "Review lineage, glossary, audit logs and access requests."]
    elif is_provider_role(user["role"]): steps = ["Check Provider Dashboard and assigned Fabric workspace.", "Register dataset by upload or external location.", "Run metadata, quality and privacy processing.", "Review My Datasets and respond to consumer requests.", "Use Data Catalog to benchmark against published assets."]
    else: steps = ["Browse Data Catalog using title, provider, domain, tag, type and size filters.", "Open public metadata and submit access request with purpose.", "Accept usage policy and complete payment.", "After approval, use token/download page and BI tool shortcuts."]
    for i, step in enumerate(steps, 1): st.markdown(f"<div class='flow-box'>{i}. {step}</div>", unsafe_allow_html=True)


def page_my_tokens_downloads():
    _ = ensure_enhanced_state()
    user = get_current_user()
    _ = show_header("My Tokens & Downloads", "Approved access, authorized masked downloads and analysis tool shortcuts.")
    tok = st.session_state.tokens[st.session_state.tokens["consumer_tenant_id"].astype(str) == str(user["tenant_id"])]
    if tok.empty:
        st.info("No active tokens yet. Request access from the Data Catalog first and complete payment after approval.")
        return
    st.dataframe(tok, width="stretch", hide_index=True)
    for _, row in tok.iterrows():
        with st.expander(f"{row['dataset_name']} | Token {row['token']}"):
            st.code(row["token"])
            st.write(f"Permission: {row['permission']} | Expiry: {row['expiry']}")
            store = st.session_state.data_store.get(row["dataset_id"], {})
            authorized = store.get("authorized")
            masked = store.get("masked")
            display_df = authorized if isinstance(authorized, pd.DataFrame) and not authorized.empty else masked
            if isinstance(display_df, pd.DataFrame):
                st.dataframe(display_df.head(10), width="stretch", hide_index=True)
                _ = dataframe_download_button(display_df, "Download authorized masked dataset",
                                              f"authorized_{row['dataset_name']}",
                                              key=f"dl_auth_{row['dataset_id']}_{row['token']}")
            st.subheader("How to explore this dataset")
            for idea in BI_TOOL_IDEAS:
                st.write(f"• {idea}")
            c1, c2, c3, c4, c5, c6 = st.columns(6)

            _ = c1.link_button("📊 Power BI", POWERBI_URL)
            _ = c2.link_button("🏗️ Microsoft Fabric", FABRIC_URL)
            _ = c3.link_button("📈 Tableau", "https://www.tableau.com/")
            _ = c4.link_button("📉 Apache Superset", "https://superset.apache.org/")
            _ = c5.link_button("🤖 Fabric Notebook", FABRIC_URL)
            _ = c6.link_button("📋 Azure ML Studio", "https://ml.azure.com/")

def _base_ensure_enhanced_state() -> None:
    _ = apply_catalog_css()
    if "business_domains" not in st.session_state:
        st.session_state.business_domains = DOMAIN_OPTIONS.copy()
    else:
        st.session_state.business_domains = clean_label_list(list(st.session_state.business_domains) + DOMAIN_OPTIONS)
    if "workspaces" not in st.session_state:
        st.session_state.workspaces = pd.DataFrame(columns=["workspace_id", "tenant_id", "tenant_name", "workspace_name", "lakehouse", "platform", "status", "fabric_url"])
    if st.session_state.workspaces.empty or "WS-TMONE" not in st.session_state.workspaces.get("workspace_id", pd.Series(dtype=str)).astype(str).tolist():
        st.session_state.workspaces = pd.concat([st.session_state.workspaces, pd.DataFrame([{"workspace_id": "WS-TMONE", "tenant_id": "T-OWNER-DEMO", "tenant_name": "TM One", "workspace_name": "TM One Monetization Lakehouse", "lakehouse": FABRIC_LAKEHOUSE_NAME, "platform": "Microsoft Fabric", "status": "Provisioned", "fabric_url": FABRIC_PORTAL_LAKEHOUSE_URL}])], ignore_index=True)
    if "sensitivity_catalog" not in st.session_state:
        st.session_state.sensitivity_catalog = pd.DataFrame([
            {"label": "Public", "severity": "Low", "policy": "Visible in catalog; purchase/access workflow still required."},
            {"label": "Internal", "severity": "Low", "policy": "Registered users only; basic audit logging."},
            {"label": "Confidential", "severity": "Medium", "policy": "Approval required; direct identifiers should be masked."},
            {"label": "Restricted", "severity": "High", "policy": "Manual governance review; short-lived token and masked preview."},
            {"label": "Highly Restricted", "severity": "Critical", "policy": "Strict approval; masked data only by default; high audit requirement."},
        ])
    if "glossary_terms" not in st.session_state:
        st.session_state.glossary_terms = pd.DataFrame([
            {"term": "Customer ID", "domain": "Customer", "definition": "Unique synthetic identifier assigned to each telecommunication subscriber.", "owner": "TM One Data Steward"},
            {"term": "Invoice ID", "domain": "Billing", "definition": "Unique synthetic invoice reference used for billing and payment analysis.", "owner": "TM One Data Steward"},
            {"term": "Service ID", "domain": "Service", "definition": "Unique synthetic identifier for a subscribed service or network service record.", "owner": "TM One Data Steward"},
            {"term": "SLA Tier", "domain": "Service", "definition": "Service level category used to compare customer service quality and commitments.", "owner": "TM One Data Steward"},
        ])
    if "lineage_edges" not in st.session_state:
        st.session_state.lineage_edges = pd.DataFrame([
            {"upstream": "Microsoft Fabric Lakehouse / owner_demo/customer.csv", "asset": "customer.csv", "downstream": "Customer Analytics Package", "relationship": "source asset"},
            {"upstream": "Microsoft Fabric Lakehouse / owner_demo/billing.csv", "asset": "billing.csv", "downstream": "Customer Analytics Package", "relationship": "source asset"},
            {"upstream": "Microsoft Fabric Lakehouse / owner_demo/service.csv", "asset": "service.csv", "downstream": "Customer Analytics Package", "relationship": "source asset"},
            {"upstream": "Customer Analytics Package", "asset": "Approved token", "downstream": "PSM UMPSA Research / BI Tools", "relationship": "governed access"},
        ])
    if "data_products" not in st.session_state:
        st.session_state.data_products = pd.DataFrame([{"product_name": "Telecommunication Customer Analytics Package", "domain": "Customer", "provider": "TM One", "datasets": "customer.csv, billing.csv, service.csv", "price_rm": 260.0, "status": "Published"}])
    if "usage_history" not in st.session_state:
        months = pd.date_range(end=pd.Timestamp.today().normalize(), periods=12, freq="ME").strftime("%Y-%m").tolist()
        st.session_state.usage_history = pd.DataFrame({"month": months, "downloads": [2,3,4,5,8,6,9,11,13,14,17,19], "revenue_rm": [0,80,80,120,200,180,260,260,320,340,420,480], "requests": [1,1,2,2,3,2,4,4,5,5,6,7]})
    if "feedback" not in st.session_state:
        st.session_state.feedback = pd.DataFrame(columns=["time", "role", "tenant", "display_name", "rating", "category", "message"])
    # Make demo dataset metadata consistent and concise.
    if len(st.session_state.datasets):
        for fname in DEMO_DATASET_FILES:
            idx = st.session_state.datasets[st.session_state.datasets["dataset_name"] == fname].index
            if len(idx):
                st.session_state.datasets.loc[idx, "description"] = CATALOG_DESCRIPTIONS.get(fname, st.session_state.datasets.loc[idx, "description"].iloc[0])
                st.session_state.datasets.loc[idx, "tags"] = CATALOG_TAGS.get(fname, st.session_state.datasets.loc[idx, "tags"].iloc[0])
                st.session_state.datasets.loc[idx, "domain"] = CATALOG_DOMAINS.get(fname, "Other")
                st.session_state.datasets.loc[idx, "catalog_title"] = CATALOG_TITLES.get(fname, fname)
        st.session_state.datasets["owner_tenant_id"] = st.session_state.datasets["owner_tenant_id"].astype(str)
    # Force PSM UMPSA tenant display.
    t_idx = st.session_state.tenants[st.session_state.tenants["tenant_id"] == "T-CONSUMER-DEMO"].index
    if len(t_idx):
        st.session_state.tenants.loc[t_idx, "tenant_name"] = "PSM UMPSA"


def user_has_dataset_access(dataset_id: str) -> bool:
    user = get_current_user()
    if user is None:
        return False
    if is_msp_role(user["role"]):
        return True  # Governance review visibility; not commercial consumption.
    ds = st.session_state.datasets[st.session_state.datasets["dataset_id"] == dataset_id]
    if not ds.empty and is_provider_role(user["role"]) and ds.iloc[0]["owner_tenant_id"] == user["tenant_id"]:
        return True
    tok = st.session_state.tokens
    return not tok[(tok["dataset_id"].astype(str) == str(dataset_id)) & (tok["consumer_tenant_id"].astype(str) == str(user["tenant_id"])) & (tok["status"].astype(str) == "Active")].empty



# =============================================================================
# Main router
# =============================================================================



def apply_sidebar_css():
    st.markdown(
        """
        <style>
        .catalog-card {background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;margin:12px 0;box-shadow:0 4px 14px rgba(15,23,42,0.055);} 
        .catalog-title {font-size:20px;font-weight:800;color:#111827;margin-bottom:7px;}
        .catalog-meta {font-size:13px;color:#475569;margin-bottom:8px;}
        .catalog-desc {font-size:14px;color:#334155;line-height:1.5;margin-top:8px;margin-bottom:10px;}
        .tag-pill {display:inline-block;padding:4px 10px;border-radius:999px;background:#eff6ff;color:#1d4ed8;font-size:12px;font-weight:650;margin:3px 5px 3px 0;border:1px solid #bfdbfe;}
        .mini-panel {background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:12px 14px;margin:8px 0;}
        .lineage-step {background:#ffffff;border:1px solid #dbeafe;border-radius:16px;padding:14px;min-height:96px;box-shadow:0 2px 8px rgba(15,23,42,0.04);} 
        .lineage-title {font-size:14px;font-weight:800;color:#1e3a8a;margin-bottom:6px;}
        .lineage-text {font-size:12px;color:#475569;line-height:1.35;}
        .small-muted {font-size:12px;color:#64748b;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _num(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _int(value, default=0):
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def _quality(value):
    return f"{_num(value):.2f}%"


def ensure_governance_support_state() -> None:
    _ = _base_ensure_enhanced_state()
    _ = apply_sidebar_css()

    # Tenant display standardization.
    if "tenants" in st.session_state:
        idx = st.session_state.tenants[st.session_state.tenants["tenant_id"] == "T-CONSUMER-DEMO"].index
        if len(idx):
            st.session_state.tenants.loc[idx, "tenant_name"] = "PSM UMPSA"

    # Core state tables used by the polished pages.
    if "feedback" not in st.session_state:
        st.session_state.feedback = pd.DataFrame(columns=["time", "role", "tenant", "display_name", "rating", "category", "message"])

    if "workspaces" not in st.session_state or st.session_state.workspaces.empty:
        st.session_state.workspaces = pd.DataFrame(columns=["workspace_id", "tenant_id", "tenant_name", "workspace_name", "lakehouse", "platform", "status", "fabric_url"])
    if "WS-TMONE" not in st.session_state.workspaces.get("workspace_id", pd.Series(dtype=str)).astype(str).tolist():
        st.session_state.workspaces = pd.concat([
            st.session_state.workspaces,
            pd.DataFrame([{
                "workspace_id": "WS-TMONE",
                "tenant_id": "T-OWNER-DEMO",
                "tenant_name": "TM One",
                "workspace_name": "TM One Monetization Lakehouse",
                "lakehouse": FABRIC_LAKEHOUSE_NAME,
                "platform": "Microsoft Fabric",
                "status": "Provisioned",
                "fabric_url": FABRIC_PORTAL_LAKEHOUSE_URL,
            }])
        ], ignore_index=True)

    st.session_state.business_domains = clean_label_list(list(st.session_state.get("business_domains", [])) + DOMAIN_OPTIONS)

    if "glossary_terms" not in st.session_state or st.session_state.glossary_terms.empty:
        st.session_state.glossary_terms = pd.DataFrame([
            {"term": "Customer ID", "domain": "Customer", "definition": "Unique synthetic identifier assigned to each telecommunication subscriber.", "owner": "Data Steward"},
            {"term": "Billing Period", "domain": "Billing", "definition": "Start and end period used to calculate subscription and usage charges.", "owner": "Data Steward"},
            {"term": "SLA Tier", "domain": "Service", "definition": "Service level category for comparing quality commitments and support priority.", "owner": "Data Steward"},
            {"term": "Access Token", "domain": "Governance", "definition": "Generated authorization reference after approval and payment simulation.", "owner": "MSP Governance"},
        ])

    if "data_products" not in st.session_state or st.session_state.data_products.empty:
        st.session_state.data_products = pd.DataFrame([
            {
                "product_name": "Telecommunication Customer Analytics Package",
                "domain": "Customer",
                "provider": "TM One",
                "datasets": "customer.csv, billing.csv, service.csv",
                "price_rm": 260.0,
                "status": "Published",
                "use_case": "Customer segmentation, revenue analysis and service quality research",
            },
            {
                "product_name": "Billing and Payment Insight Product",
                "domain": "Billing",
                "provider": "TM One",
                "datasets": "billing.csv",
                "price_rm": 80.0,
                "status": "Published",
                "use_case": "Revenue tracking and payment behavior analysis",
            },
        ])

    if "lineage_edges" not in st.session_state or st.session_state.lineage_edges.empty:
        st.session_state.lineage_edges = pd.DataFrame([
            {"upstream": "Source Platform", "asset": "Raw Dataset", "downstream": "Metadata Discovery", "relationship": "registered source"},
            {"upstream": "Metadata Discovery", "asset": "Privacy and Quality Scan", "downstream": "Data Catalog", "relationship": "governance processing"},
            {"upstream": "Data Catalog", "asset": "Access Request", "downstream": "Approved Access Token", "relationship": "approval workflow"},
            {"upstream": "Approved Access Token", "asset": "Authorized Dataset", "downstream": "Analytics and Research", "relationship": "governed consumption"},
        ])

    if "usage_history" not in st.session_state or st.session_state.usage_history.empty:
        months = pd.date_range(end=pd.Timestamp.today().normalize(), periods=12, freq="MS").strftime("%Y-%m").tolist()
        st.session_state.usage_history = pd.DataFrame({
            "month": months,
            "downloads": [2, 3, 4, 5, 8, 6, 9, 11, 13, 14, 17, 19],
            "requests": [1, 1, 2, 2, 3, 2, 4, 4, 5, 5, 6, 7],
            "revenue_rm": [0, 80, 80, 120, 200, 180, 260, 260, 320, 340, 420, 480],
        })

    # Dataset catalog metadata and consistency.
    if "datasets" in st.session_state and len(st.session_state.datasets):
        for col, default in {
            "domain": "Other",
            "pii_declaration": "Unsure",
            "data_location_type": "External platform reference",
            "usage_policy_version": "v1.0",
            "catalog_title": "",
            "asset_type": "CSV",
            "view_count": 0,
        }.items():
            if col not in st.session_state.datasets.columns:
                st.session_state.datasets[col] = default

        demo_view_counts = {"customer.csv": 124, "billing.csv": 96, "service.csv": 88}
        demo_download_counts = {"customer.csv": 14, "billing.csv": 11, "service.csv": 9}
        for fname in DEMO_DATASET_FILES:
            idx = st.session_state.datasets[st.session_state.datasets["dataset_name"].astype(str).str.lower().eq(fname)].index
            if len(idx):
                st.session_state.datasets.loc[idx, "catalog_title"] = CATALOG_TITLES.get(fname, fname)
                st.session_state.datasets.loc[idx, "description"] = CATALOG_DESCRIPTIONS.get(fname, st.session_state.datasets.loc[idx, "description"].iloc[0])
                st.session_state.datasets.loc[idx, "tags"] = CATALOG_TAGS.get(fname, st.session_state.datasets.loc[idx, "tags"].iloc[0])
                st.session_state.datasets.loc[idx, "domain"] = CATALOG_DOMAINS.get(fname, "Other")
                st.session_state.datasets.loc[idx, "asset_type"] = "CSV"
                st.session_state.datasets.loc[idx, "source_platform"] = "Microsoft Fabric Lakehouse"
                st.session_state.datasets.loc[idx, "view_count"] = demo_view_counts.get(fname, 0)
                if "download_count" in st.session_state.datasets.columns:
                    st.session_state.datasets.loc[idx, "download_count"] = st.session_state.datasets.loc[idx, "download_count"].replace(0, demo_download_counts.get(fname, 0))

    if "access_requests" in st.session_state:
        for col, default in {"accepted_policy": True, "purpose_detail": ""}.items():
            if col not in st.session_state.access_requests.columns:
                st.session_state.access_requests[col] = default

def role_quick_guide(role: str) -> str:
    match = ROLE_DESCRIPTIONS[ROLE_DESCRIPTIONS["Role"] == role]
    if not match.empty:
        return str(match.iloc[0]["Purpose"])
    return "Navigate the platform features based on your assigned role."

def catalog_datasets_for_user(user: Dict) -> pd.DataFrame:
    ds = st.session_state.datasets.copy()
    if ds.empty:
        return ds
    if is_msp_role(user["role"]):
        # Hide Drafts from MSP in the global catalog.
        return ds[ds["status"].astype(str) != "Draft"]
    if is_provider_role(user["role"]):
        own = ds["owner_tenant_id"].astype(str).eq(str(user["tenant_id"]))
        published = ds["status"].astype(str).eq("Published")
        return ds[own | published]
    return ds[ds["status"].astype(str).eq("Published")]


def _access_flags(row, user: Dict):
    is_msp = is_msp_role(user["role"])
    is_owner_provider = is_provider_role(user["role"]) and str(row.get("owner_tenant_id")) == str(user.get("tenant_id"))
    consumer_token = False
    if is_consumer_role(user["role"]) and "tokens" in st.session_state and len(st.session_state.tokens):
        token_rows = st.session_state.tokens[
            (st.session_state.tokens["dataset_id"].astype(str) == str(row.get("dataset_id"))) &
            (st.session_state.tokens["consumer_tenant_id"].astype(str) == str(user.get("tenant_id"))) &
            (st.session_state.tokens["status"].astype(str) == "Active")
        ]
        consumer_token = not token_rows.empty
    return is_msp, is_owner_provider, consumer_token






def page_data_catalog():
    _ = ensure_enhanced_state()
    _ = show_header("Data Catalog", "Discover governed datasets, compare metadata and request access through the catalog workflow.")
    user = get_current_user()
    ds = catalog_datasets_for_user(user).copy()
    if ds.empty:
        st.info("No datasets available.")
        return

    for col, default in {"domain": "Other", "asset_type": "CSV", "catalog_title": ""}.items():
        if col not in ds.columns:
            ds[col] = default
    ds["display_title"] = ds.apply(catalog_title, axis=1)
    ds["provider_name"] = ds["owner_tenant_id"].apply(tenant_name)

    c1, c2, c3 = st.columns([1, 1, 1])
    title_search = c1.text_input("Search title", placeholder="telecommunication")
    provider_search = c2.text_input("Search provider", placeholder="TM One")
    available_domains = get_available_domains(include_other=True)
    domain_filter = c3.multiselect("Domain", available_domains, default=[])
    c4, c5, c6 = st.columns([1, 1, 1])
    tag_filter = c4.multiselect("Tags", TAG_OPTIONS, default=[])
    type_filter = c5.multiselect("File / dataset type", ASSET_TYPE_OPTIONS, default=[])
    sort_by = c6.selectbox("Sort by", ["Relevance", "Trending", "Most downloaded", "Quality score", "Price: low to high", "Price: high to low", "A to Z", "Z to A", "Rows: high to low"])

    r1, r2 = st.columns(2)

    min_rows = r1.number_input(
        "Minimum Rows",
        min_value=0,
        value=0,
        step=1
    )

    min_cols = r2.number_input(
        "Minimum Columns",
        min_value=0,
        value=0,
        step=1
    )

    filtered = ds.copy()
    if title_search:
        q = title_search.lower().strip()
        filtered = filtered[filtered.apply(lambda r: q in str(r.get("display_title", "")).lower() or q in str(r.get("dataset_name", "")).lower(), axis=1)]
    if provider_search:
        q = provider_search.lower().strip()
        filtered = filtered[filtered["provider_name"].str.lower().str.contains(q, na=False)]
    if domain_filter:
        filtered = filtered[filtered["domain"].isin(domain_filter)]
    if tag_filter:
        filtered = filtered[filtered["tags"].apply(lambda t: any(tag.lower() in str(t).lower() for tag in tag_filter))]
    if type_filter:
        filtered = filtered[filtered["format"].isin(type_filter) | filtered.get("asset_type", pd.Series(index=filtered.index, dtype=str)).isin(type_filter)]
    filtered = filtered[
        filtered["rows"].astype(float).fillna(0) >= min_rows
        ]

    filtered = filtered[
        filtered["columns"].astype(float).fillna(0) >= min_cols
        ]
    if sort_by == "Trending":
        filtered = filtered.sort_values(["view_count", "download_count"], ascending=False)
    elif sort_by == "Most downloaded":
        filtered = filtered.sort_values("download_count", ascending=False)
    elif sort_by == "Quality score":
        filtered = filtered.sort_values("quality_score", ascending=False)
    elif sort_by == "Price: low to high":
        filtered = filtered.sort_values("price_rm")
    elif sort_by == "Price: high to low":
        filtered = filtered.sort_values("price_rm", ascending=False)
    elif sort_by == "A to Z":
        filtered = filtered.sort_values("display_title")
    elif sort_by == "Z to A":
        filtered = filtered.sort_values("display_title", ascending=False)
    elif sort_by == "Rows: high to low":
        filtered = filtered.sort_values("rows", ascending=False)

    st.write(f"**{len(filtered)} datasets found**")
    for _, row in filtered.iterrows():
        _ = render_catalog_card(row, user)


def draw_lineage_flow(dataset_name: str = "Dataset"):
    steps = [
        ("Source Platform", "Fabric / ADLS / S3 / database / API registered by provider"),
        ("Dataset", str(dataset_name)),
        ("Metadata Discovery", "Rows, columns, schema, format and source reference"),
        ("Privacy & Quality", "PII detection, classification, quality score and masking"),
        ("Data Product", "Curated package prepared for catalog discovery"),
        ("Data Catalog", "Searchable metadata, pricing, policy and access workflow"),
        ("Access Control", "Request approval, payment simulation and token generation"),
        ("Analytics", "Power BI, Fabric notebooks, Python or research analysis"),
    ]
    cols = st.columns(4)
    for idx, (title, text) in enumerate(steps):
        with cols[idx % 4]:
            st.markdown(f"<div class='lineage-step'><div class='lineage-title'>{idx+1}. {title}</div><div class='lineage-text'>{text}</div></div>", unsafe_allow_html=True)


def page_lineage_glossary():
    _ = ensure_enhanced_state()
    _ = show_header("Lineage, Glossary & Data Products", "Catalog governance features inspired by Purview Catalog.")
    tab1, tab2, tab3, tab4 = st.tabs(["Lineage", "Business Glossary", "Data Products", "Domains"])
    with tab1:
        st.subheader("Dataset-centric lineage")
        dataset_options = st.session_state.datasets["dataset_name"].astype(str).tolist() if len(st.session_state.datasets) else ["Dataset"]
        selected = st.selectbox("Select asset", dataset_options)
        _ = draw_lineage_flow(selected)
        st.markdown("### Lineage evidence table")
        st.dataframe(st.session_state.lineage_edges, width="stretch", hide_index=True)
    with tab2:
        st.dataframe(st.session_state.glossary_terms, width="stretch", hide_index=True)
        if is_msp_role(get_current_user()["role"]) or is_provider_role(get_current_user()["role"]):
            with st.form("add_glossary_term_form"):
                term = st.text_input("Term")
                domain = st.selectbox("Domain", get_available_domains(include_other=True))
                definition = st.text_area("Definition")
                owner = st.text_input("Owner", value=get_current_user()["name"])
                if st.form_submit_button("Add glossary term"):
                    if not term or not definition:
                        st.warning("Please provide both term and definition.")
                    else:
                        new = pd.DataFrame([{"term": term, "domain": domain, "definition": definition, "owner": owner}])
                        st.session_state.glossary_terms = pd.concat([st.session_state.glossary_terms, new], ignore_index=True)
                        st.success("Glossary term added.")
                        st.rerun()
    with tab3:
        st.dataframe(st.session_state.data_products, width="stretch", hide_index=True)
        for _, product in st.session_state.data_products.iterrows():
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                _ = c1.markdown(f"**{product['product_name']}**")
                _ = c1.write(f"Domains: {product.get('domains', product.get('domain', 'General'))} | Provider: {product['provider']}")
                _ = c1.write(f"Datasets: {product['datasets']}")
                if "use_case" in product:
                    _ = c1.caption(str(product["use_case"]))
                _ = c2.metric("Price", f"RM {_num(product.get('price_rm',0)):,.2f}")
                _ = c2.write(product.get("status", ""))
    with tab4:
        st.write("Available governance domains for future catalog expansion:")
        domain_df = pd.DataFrame({"domain": get_available_domains(include_other=False)})
        st.dataframe(domain_df, width="stretch", hide_index=True)
        if is_msp_role(get_current_user()["role"]) or is_provider_role(get_current_user()["role"]):
            with st.form("add_business_domain_form"):
                new_domain = st.text_input("Add business domain")
                submitted = st.form_submit_button("Add domain")
                if submitted:
                    added_domain = add_business_domain(new_domain)
                    if added_domain:
                        add_log(get_current_user()["email"], f"Added business domain {added_domain}", get_current_user()["tenant_id"])
                        st.success(f"Domain added: {added_domain}")
                        st.rerun()
                    else:
                        st.warning("Please enter a domain name.")


def page_provider_analytics():
    _ = ensure_enhanced_state()
    user = get_current_user()
    _ = show_header("Usage, request and revenue view for provider datasets.")
    ds = st.session_state.datasets[st.session_state.datasets["owner_tenant_id"].astype(str) == str(user["tenant_id"])].copy()
    req = st.session_state.access_requests[st.session_state.access_requests["dataset_id"].isin(ds["dataset_id"])] if len(ds) and len(st.session_state.access_requests) else pd.DataFrame()
    usage = st.session_state.usage_history.copy()
    c1, c2, c3, c4 = st.columns(4)
    _ = c1.metric("Datasets", len(ds))
    _ = c2.metric("Requests", len(req))
    _ = c3.metric("Approved", int((req["status"] == "Approved").sum()) if len(req) else 0)
    _ = c4.metric("Revenue", f"RM {_num(ds.get('provider_revenue_rm', pd.Series([0])).sum() if len(ds) else 0):,.2f}")
    left, right = st.columns(2)
    with left:
        st.subheader("Downloads trend")
        if not usage.empty:
            st.line_chart(usage.set_index("month")[["downloads"]])
    with right:
        st.subheader("Revenue trend")
        if not usage.empty:
            st.line_chart(usage.set_index("month")[["revenue_rm"]])
    st.subheader("Dataset popularity")
    if len(ds):
        popularity_cols = ["dataset_name", "download_count", "view_count", "quality_score", "price_rm", "status"]
        st.dataframe(ds[[c for c in popularity_cols if c in ds.columns]].sort_values("download_count", ascending=False), width="stretch", hide_index=True)


def page_account_management():
    _ = ensure_enhanced_state()
    user = get_current_user()
    _ = show_header("Account Management", "Tenant administrators can create sub-accounts within their own organization.")
    if user["role"] not in ["Provider Administrator", "Consumer Administrator", "MSP Administrator"]:
        st.error("Only tenant administrators can create sub-accounts.")
        return
    tenant_id = user["tenant_id"]
    tenant_type = get_user_tenant_type(user)
    allowed_roles = roles_for_tenant_type(tenant_type)
    current = st.session_state.users[st.session_state.users["tenant_id"].astype(str) == str(tenant_id)].drop(columns=["password_hash"], errors="ignore")
    st.dataframe(current, width="stretch", hide_index=True)
    with st.form("create_sub_account_form"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Full name")
            email = st.text_input("Email")
        with c2:
            role = st.selectbox("Role", allowed_roles)
            password = st.text_input("Temporary password", value="password123", type="password")
        submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            if not name or not email or not password:
                st.error("Please complete all fields.")
            elif email.lower() in st.session_state.users["email"].str.lower().tolist():
                st.error("Email already exists.")
            else:
                new_user = pd.DataFrame([{"email": email.lower(), "name": name, "password_hash": hash_password(password), "role": role, "tenant_id": tenant_id, "status": "Active"}])
                st.session_state.users = pd.concat([st.session_state.users, new_user], ignore_index=True)
                _ = add_log(user["email"], f"Created sub-account {email} as {role}", tenant_id)
                st.success("Account created.")
                st.rerun()





def page_feedback():
    _ = ensure_enhanced_state()
    user = get_current_user()

    if is_msp_role(user["role"]):
        _ = show_header("Feedback", "Feedback and ratings submitted by data providers and data consumers.")
        if st.session_state.feedback.empty:
            st.info("No feedback submitted yet.")
        else:
            c1, c2, c3 = st.columns(3)
            _ = c1.metric("Total feedback", len(st.session_state.feedback))
            _ = c2.metric("Average rating", f"{float(st.session_state.feedback['rating'].mean()):.2f} / 10")
            _ = c3.metric("Latest", str(st.session_state.feedback["time"].max()))
            st.dataframe(st.session_state.feedback.sort_values("time", ascending=False), width="stretch", hide_index=True)
        return

    _ = show_header("Feedback", "Share feedback about the platform experience.")

    with st.form("feedback_form"):
        rating = st.slider("Rating", 1, 10, 8, help="Rate the platform experience from 1 to 10 stars.")
        category = st.selectbox("Category", ["Data Catalog", "Dataset Registration", "Access Request", "Dashboard", "Policy & Governance", "Usability", "Other"])
        message = st.text_area("Feedback")
        show_name = st.radio("Display name to MSP", ["Anonymous", "Show my name"], horizontal=True)
        if st.form_submit_button("Submit feedback", type="primary"):
            if not message.strip():
                st.warning("Please write your feedback before submitting.")
            else:
                display_name = user["name"] if show_name == "Show my name" else "Anonymous"
                new = pd.DataFrame([{
                    "time": now_str(),
                    "role": user["role"],
                    "tenant": tenant_name(user["tenant_id"]),
                    "display_name": display_name,
                    "rating": rating,
                    "category": category,
                    "message": message.strip(),
                }])
                st.session_state.feedback = pd.concat([st.session_state.feedback, new], ignore_index=True)
                _ = add_log(user["email"], "Submitted platform feedback", user["tenant_id"])
                st.success("Feedback submitted. Thank you.")

    st.info(
        "We would appreciate if you could also fill in our Microsoft Forms feedback survey for future improvement."
    )

    st.link_button(
        "📝 Fill in Official Microsoft Forms Survey",
        "https://forms.office.com/r/iMzrg1X4X3"
    )


def page_register_dataset():
    _ = ensure_enhanced_state()
    user = get_current_user()
    _ = show_header("Register Dataset",
                    "Register a dataset by uploading a file for prototype scanning or linking to an external platform location.")

    st.subheader("1. Source location")
    location_type = st.radio(
        "Where is the data currently located?",
        ["Upload file here for prototype scanning", "Connect / register external platform location"],
        horizontal=True,
        key="register_location_type",
    )

    upload_file = None
    source_platform = "Local prototype upload"
    source_uri = ""
    fmt = "Unknown"
    connection_name = ""
    connection_details = {}

    if location_type == "Upload file here for prototype scanning":
        st.info(
            "Upload is used only for prototype metadata, quality and privacy scanning. In the real platform, the physical data can remain in Fabric, ADLS, S3, database, API or another governed source.")
        upload_file = st.file_uploader("Upload dataset file", type=["csv", "xlsx", "xls", "json", "parquet"],
                                       key="register_upload_file")
        if upload_file is not None:
            fmt = upload_file.name.split(".")[-1].upper()
            source_uri = upload_file.name
    else:
        st.info(
            "Use this when the dataset already exists in an external platform. The catalog stores metadata, source reference, policy and token workflow, not the large physical dataset itself.")
        c1, c2 = st.columns(2)
        with c1:
            source_platform = st.selectbox("Source platform", CONNECTION_SOURCE_PLATFORMS,
                                           key="external_source_platform")
            fmt = st.selectbox("File / dataset type", ASSET_TYPE_OPTIONS, key="external_asset_type")
            connection_name = st.text_input("Connection name", placeholder="Example: TM One Fabric Lakehouse",
                                            key="external_connection_name")
        with c2:
            source_uri = st.text_input("Storage URL / path / endpoint",
                                       placeholder="OneLake URL, ABFSS path, S3 URI, database table, or API endpoint",
                                       key="external_source_uri")
            auth_method = st.selectbox("Access method",
                                       ["Managed identity", "Service principal", "Shared access signature", "API key",
                                        "Database credential", "Manual reference only"], key="external_auth_method")
            refresh_mode = st.selectbox("Metadata refresh", ["Manual scan", "Daily", "Weekly", "Monthly", "On demand"],
                                        key="external_refresh_mode")

        with st.expander("Optional external source details", expanded=False):
            d1, d2, d3 = st.columns(3)
            workspace_or_bucket = d1.text_input("Workspace / bucket / account", key="external_workspace_bucket")
            database_or_lakehouse = d2.text_input("Database / lakehouse / container", key="external_database_lakehouse")
            schema_or_folder = d3.text_input("Schema / folder / API route", key="external_schema_folder")
            connection_details = {
                "connection_name": connection_name,
                "access_method": auth_method,
                "metadata_refresh": refresh_mode,
                "workspace_or_bucket": workspace_or_bucket,
                "database_or_lakehouse": database_or_lakehouse,
                "schema_or_folder": schema_or_folder,
            }

    st.subheader("2. Catalog metadata")
    with st.form("register_dataset_form"):
        c1, c2 = st.columns(2)
        with c1:
            title = st.text_input("Catalog title")
            domain_choice = st.selectbox("Domain", get_available_domains(include_other=True))
            custom_domain = ""
            if domain_choice == "Other":
                custom_domain = st.text_input("Custom domain name")
            pii_declaration = st.selectbox("Does the dataset contain PII?", ["Yes", "No", "Unsure"])
        with c2:
            price_rm = st.number_input("Dataset price (RM)", min_value=0.0, value=100.0, step=10.0)
            selected_tags = st.multiselect("Business tags", TAG_OPTIONS, default=[],
                                           help="Select business-domain, use-case, geography, or industry tags. Avoid technical/governance tags such as masked, quality checked, or PII.")
            custom_tags = st.text_input("Provider-defined tags (comma separated)",
                                        help="Add your own business-friendly tags, for example a product line, department, or project name.")
        description = st.text_area("Business description",
                                   placeholder="Describe the dataset, business meaning, expected use cases and key columns.")

        st.markdown("**Provider publication policy:**")
        for term in PROVIDER_USAGE_TERMS:
            st.write(f"• {term}")
        accepted = st.checkbox("I accept the provider publication policy.")
        submitted = st.form_submit_button("Run metadata, quality and privacy processing", type="primary")

    if submitted:
        if not title.strip():
            st.error("Please enter a catalog title.")
            return
        if not accepted:
            st.error("Please accept the provider publication policy.")
            return

        if location_type == "Upload file here for prototype scanning":
            if upload_file is None:
                st.error("Please upload a file for prototype scanning.")
                return
            raw_df, fmt, msg = safe_read_upload(upload_file)
            source_uri = upload_file.name
            source_platform = "Streamlit prototype upload"
            if raw_df is None:
                st.error(msg)
                return
        else:
            if not source_uri.strip():
                st.error("Please enter the external storage URL, path, table name, or endpoint reference.")
                return
            raw_df = pd.DataFrame({
                "metadata_reference": [source_uri],
                "source_platform": [source_platform],
                "asset_type": [fmt],
                "connection_name": [connection_name],
                "registration_mode": ["external platform reference"],
                "access_method": [connection_details.get("access_method", "")],
                "metadata_refresh": [connection_details.get("metadata_refresh", "")],
            })

        domain = add_business_domain(custom_domain) if domain_choice == "Other" else add_business_domain(domain_choice)
        if not domain:
            st.error("Please select or enter a domain name.")
            return

        tags = ", ".join(clean_label_list(
            [t.strip() for t in selected_tags] + [t.strip() for t in custom_tags.split(",") if t.strip()]))
        processed = process_dataset(raw_df, title, source_platform, fmt, source_uri)
        provider_note = "Registered through provider workflow. "
        if location_type == "Connect / register external platform location":
            provider_note += f"External source details: {json.dumps(connection_details)}"
        else:
            provider_note += "Prototype file upload used for metadata, quality and privacy scanning."

        ds_id = add_dataset_record(
            dataset_name=title,
            description=description or "Registered dataset for governed catalog publication.",
            owner_email=user["email"],
            owner_tenant_id=user["tenant_id"],
            registration_method=(
                "File Upload" if location_type == "Upload file here for prototype scanning" else default_registration_method_for_source(
                    source_platform)),
            source_platform=source_platform,
            fmt=fmt,
            source_uri=source_uri,
            processed=processed,
            price_rm=price_rm,
            is_paid=True,
            tags=tags,
            provider_internal_note=provider_note,
            status=None,
        )
        idx = st.session_state.datasets[st.session_state.datasets["dataset_id"] == ds_id].index
        st.session_state.datasets.loc[idx, "catalog_title"] = title
        st.session_state.datasets.loc[idx, "domain"] = domain
        st.session_state.datasets.loc[idx, "pii_declaration"] = pii_declaration
        st.session_state.datasets.loc[idx, "asset_type"] = fmt
        st.session_state.datasets.loc[idx, "data_location_type"] = location_type
        if location_type == "Connect / register external platform location":
            st.session_state.metadata_store[ds_id]["External Source Details"] = json.dumps(connection_details)

        _ = add_log(user["email"], f"Registered dataset {title} and ran processing", user["tenant_id"])

        st.session_state.newly_registered_dataset_id = ds_id
        save_prototype_state()
        st.rerun()

    if st.session_state.get("newly_registered_dataset_id"):
        ds_id = st.session_state.newly_registered_dataset_id

        if not st.session_state.datasets[st.session_state.datasets["dataset_id"] == ds_id].empty:
            st.markdown("---")
            st.success("Dataset processed successfully and saved as a Draft package.")

            with st.expander("Registration Result & Publication Action", expanded=True):
                _ = render_dataset_detail(ds_id, allow_data_preview=True)

            if st.button("Dismiss and register another dataset", key="clear_registration_view"):
                st.session_state.newly_registered_dataset_id = None
                st.rerun()

DIRECT_PURCHASE_CLASSIFICATIONS = ["Public", "Internal"]
PROVIDER_APPROVAL_CLASSIFICATIONS = ["Confidential"]
JOINT_APPROVAL_CLASSIFICATIONS = ["Restricted", "Highly Restricted"]


def access_workflow_for_classification(classification: str) -> dict:
    classification = str(classification or "Internal")
    if classification in DIRECT_PURCHASE_CLASSIFICATIONS:
        return {
            "action": "Purchase",
            "button": "Purchase Dataset",
            "status": "Direct Purchase",
            "requires_provider": False,
            "requires_msp": False,
            "message": "Direct purchase is allowed because this dataset is not classified as sensitive.",
            "token_days": 90,
        }
    if classification in PROVIDER_APPROVAL_CLASSIFICATIONS:
        return {
            "action": "Request Access",
            "button": "Request Access",
            "status": "Pending Provider Approval",
            "requires_provider": True,
            "requires_msp": False,
            "message": "Provider approval is required because the dataset contains confidential business or personal information.",
            "token_days": 60,
        }
    return {
        "action": "Request Access",
        "button": "Request Access",
        "status": "Pending Provider/MSP Approval",
        "requires_provider": True,
        "requires_msp": True,
        "message": "Provider support and MSP/Governance approval are required because this dataset is restricted or highly restricted.",
        "token_days": 30,
    }


def ensure_policy_reference_tables() -> None:
    default_labels = pd.DataFrame([
        {"label": "Public", "severity": "Low", "approval_workflow": "Direct purchase", "policy": "Visible in catalog. Consumer may purchase directly after accepting usage terms."},
        {"label": "Internal", "severity": "Low", "approval_workflow": "Direct purchase", "policy": "Visible to registered tenants. Direct purchase allowed; access token and download activity are logged."},
        {"label": "Confidential", "severity": "Medium", "approval_workflow": "Provider approval", "policy": "Provider Data Owner approval required. Direct identifiers must be masked before access."},
        {"label": "Restricted", "severity": "High", "approval_workflow": "Provider + MSP approval", "policy": "Provider support and MSP review required. Short-lived token, masking, and audit monitoring are enforced."},
        {"label": "Highly Restricted", "severity": "Critical", "approval_workflow": "Provider + Governance approval", "policy": "Strict governance approval required. Default access is masked sample only unless exception is approved."},
    ])

    if "sensitivity_catalog" not in st.session_state or st.session_state.sensitivity_catalog.empty:
        st.session_state.sensitivity_catalog = default_labels.copy()
    else:
        existing_cols = list(st.session_state.sensitivity_catalog.columns)
        if "approval_workflow" not in existing_cols:
            label_map = dict(zip(default_labels["label"], default_labels["approval_workflow"]))
            st.session_state.sensitivity_catalog["approval_workflow"] = st.session_state.sensitivity_catalog["label"].map(label_map).fillna("Policy-defined")
        if len(st.session_state.sensitivity_catalog) <= 5 and set(default_labels["label"]).issuperset(set(st.session_state.sensitivity_catalog["label"].astype(str))):
            st.session_state.sensitivity_catalog = default_labels.copy()

    default_sensitive_types = pd.DataFrame([
        {"sensitive_type": "Malaysia NRIC", "default_classification": "Highly Restricted", "masking_policy": "Full Mask", "approval_workflow": "Provider + Governance approval", "token_days": 30, "policy": "Government identifier; release only masked value unless a governance exception is approved."},
        {"sensitive_type": "Passport Number", "default_classification": "Highly Restricted", "masking_policy": "Full Mask", "approval_workflow": "Provider + Governance approval", "token_days": 30, "policy": "Government identifier; full masking and strict approval required."},
        {"sensitive_type": "Credit Card Number", "default_classification": "Highly Restricted", "masking_policy": "Full Mask", "approval_workflow": "Provider + Governance approval", "token_days": 30, "policy": "Payment identifier; full masking and high-risk review required."},
        {"sensitive_type": "Biometric Information", "default_classification": "Highly Restricted", "masking_policy": "Full Mask", "approval_workflow": "Provider + Governance approval", "token_days": 30, "policy": "Sensitive personal data; strict approval and minimized access required."},
        {"sensitive_type": "Health Information", "default_classification": "Highly Restricted", "masking_policy": "Full Mask", "approval_workflow": "Provider + Governance approval", "token_days": 30, "policy": "Sensitive health-related data; strict governance approval required."},
        {"sensitive_type": "Government Identifier", "default_classification": "Restricted", "masking_policy": "Full Mask", "approval_workflow": "Provider + MSP approval", "token_days": 30, "policy": "Government-related identifier; manual review and short-lived token required."},
        {"sensitive_type": "Email Address", "default_classification": "Confidential", "masking_policy": "Partial Mask", "approval_workflow": "Provider approval", "token_days": 60, "policy": "Direct contact identifier; partial masking recommended for preview and provider approval for access."},
        {"sensitive_type": "Phone Number", "default_classification": "Confidential", "masking_policy": "Partial Mask", "approval_workflow": "Provider approval", "token_days": 60, "policy": "Direct contact identifier; partial masking recommended for preview and provider approval for access."},
        {"sensitive_type": "Person Name", "default_classification": "Confidential", "masking_policy": "Partial Mask", "approval_workflow": "Provider approval", "token_days": 60, "policy": "Direct personal identifier; provider review required before release."},
        {"sensitive_type": "Address / Location", "default_classification": "Confidential", "masking_policy": "Preserve / Generalize", "approval_workflow": "Provider approval", "token_days": 60, "policy": "Location attribute; generalize when possible and require provider approval for detailed access."},
        {"sensitive_type": "Financial Information", "default_classification": "Confidential", "masking_policy": "Partial Mask / Aggregate", "approval_workflow": "Provider approval", "token_days": 60, "policy": "Commercial or payment-related data; provider approval and audit logging required."},
        {"sensitive_type": "Date / Time", "default_classification": "Internal", "masking_policy": "Preserve", "approval_workflow": "Direct purchase", "token_days": 90, "policy": "Usually low risk alone; may become confidential when combined with direct identifiers."},
    ])
    if "sensitive_data_types" not in st.session_state or st.session_state.sensitive_data_types.empty:
        st.session_state.sensitive_data_types = default_sensitive_types.copy()

    default_policies = pd.DataFrame([
        {"policy_id": "POL-ACCESS-001", "policy_type": "Access Policy", "policy_name": "Public Dataset Direct Purchase", "rule": "Public datasets can be purchased directly after usage terms are accepted; token is generated automatically.", "enabled": True},
        {"policy_id": "POL-ACCESS-002", "policy_type": "Access Policy", "policy_name": "Internal Dataset Direct Purchase", "rule": "Internal datasets can be purchased directly by registered tenants; token and download activity are logged.", "enabled": True},
        {"policy_id": "POL-ACCESS-003", "policy_type": "Access Policy", "policy_name": "Confidential Provider Approval", "rule": "Confidential datasets require approval from the provider Data Owner or Provider Administrator.", "enabled": True},
        {"policy_id": "POL-ACCESS-004", "policy_type": "Access Policy", "policy_name": "Restricted Dual Approval", "rule": "Restricted datasets require provider support followed by MSP or Governance approval.", "enabled": True},
        {"policy_id": "POL-ACCESS-005", "policy_type": "Access Policy", "policy_name": "Highly Restricted Governance Approval", "rule": "Highly Restricted datasets require provider support and Governance Administrator approval.", "enabled": True},
        {"policy_id": "POL-MASK-001", "policy_type": "Masking Policy", "policy_name": "Full Mask Government Identifiers", "rule": "NRIC, passport, credit card and similar regulated identifiers are fully masked by default.", "enabled": True},
        {"policy_id": "POL-MASK-002", "policy_type": "Masking Policy", "policy_name": "Partial Mask Direct Contact Identifiers", "rule": "Email, phone number and person name use partial masking in previews and sample downloads.", "enabled": True},
        {"policy_id": "POL-MASK-003", "policy_type": "Masking Policy", "policy_name": "Masked Preview Before Approval", "rule": "Consumers may only view public metadata before approval; sensitive details and raw data remain hidden.", "enabled": True},
        {"policy_id": "POL-RET-001", "policy_type": "Retention Policy", "policy_name": "Standard Token Expiry", "rule": "Public and Internal tokens expire after 90 days unless renewed.", "enabled": True},
        {"policy_id": "POL-RET-002", "policy_type": "Retention Policy", "policy_name": "Sensitive Token Expiry", "rule": "Confidential tokens expire after 60 days; Restricted and Highly Restricted tokens expire after 30 days.", "enabled": True},
        {"policy_id": "POL-COMP-001", "policy_type": "Compliance Policy", "policy_name": "PDPA-Aligned Privacy Review", "rule": "Sensitive personal data requires privacy review, masking and access audit logging.", "enabled": True},
        {"policy_id": "POL-COMP-002", "policy_type": "Compliance Policy", "policy_name": "Purpose Limitation", "rule": "Consumer access must be used only for the approved purpose stated in the access request.", "enabled": True},
        {"policy_id": "POL-COMP-003", "policy_type": "Compliance Policy", "policy_name": "No Redistribution", "rule": "Consumers may not redistribute, resell or publish raw dataset contents without provider approval.", "enabled": True},
        {"policy_id": "POL-AUDIT-001", "policy_type": "Audit Policy", "policy_name": "Access and Download Logging", "rule": "Token generation, download count, approval decisions and usage activity are logged for audit.", "enabled": True},
        {"policy_id": "POL-REV-001", "policy_type": "Revenue Policy", "policy_name": "MSP Platform Commission", "rule": f"Credence retains {MSP_COMMISSION_RATE:.0%} platform commission from approved paid dataset purchases.", "enabled": True},
    ])

    if "policies" not in st.session_state or st.session_state.policies.empty:
        st.session_state.policies = default_policies.copy()
    else:
        old_policy_names = set(st.session_state.policies.get("policy_name", pd.Series(dtype=str)).astype(str).tolist())
        if {"Government Email Only", "University Email Only"}.intersection(old_policy_names) or len(st.session_state.policies) <= 6:
            st.session_state.policies = default_policies.copy()


def ensure_demo_revenue_alignment() -> None:
    if "usage_history" not in st.session_state or st.session_state.usage_history.empty:
        return
    months = pd.date_range(end=pd.Timestamp.today().normalize(), periods=12, freq="MS").strftime("%Y-%m").tolist()
    base_usage = pd.DataFrame({
        "month": months,
        "downloads": [1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 7, 8],
        "requests": [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 5],
        "revenue_rm": [80, 120, 160, 180, 220, 240, 260, 300, 330, 360, 400, 450],
    })

    if not st.session_state.get("demo_revenue_seeded", False):
        st.session_state.usage_history = base_usage.copy()
        demo_counts = {"customer.csv": 14, "billing.csv": 11, "service.csv": 9}
        demo_classes = {"customer.csv": "Confidential", "billing.csv": "Confidential", "service.csv": "Internal"}
        demo_titles = {
            "customer.csv": "Telecommunication Customer Profile Dataset",
            "billing.csv": "Telecommunication Billing and Payment Dataset",
            "service.csv": "Telecommunication Service Subscription Dataset",
        }
        for fname, downloads in demo_counts.items():
            idx = st.session_state.datasets[st.session_state.datasets["dataset_name"].astype(str).str.lower().eq(fname)].index
            if len(idx):
                price = float(pd.to_numeric(st.session_state.datasets.loc[idx, "price_rm"], errors="coerce").fillna(0).iloc[0])
                revenue = round(price * downloads, 2)
                commission = round(revenue * MSP_COMMISSION_RATE, 2)
                st.session_state.datasets.loc[idx, "download_count"] = downloads
                st.session_state.datasets.loc[idx, "revenue_rm"] = revenue
                st.session_state.datasets.loc[idx, "msp_commission_rm"] = commission
                st.session_state.datasets.loc[idx, "provider_revenue_rm"] = round(revenue - commission, 2)
                st.session_state.datasets.loc[idx, "classification"] = demo_classes.get(fname, st.session_state.datasets.loc[idx, "classification"].iloc[0])
                st.session_state.datasets.loc[idx, "catalog_title"] = demo_titles.get(fname, st.session_state.datasets.loc[idx, "catalog_title"].iloc[0])
        st.session_state.demo_revenue_seeded = True


def ensure_catalog_support_state() -> None:
    _ = ensure_governance_support_state()
    _ = ensure_policy_reference_tables()
    _ = ensure_demo_revenue_alignment()

    # Access request governance columns.
    if "access_requests" in st.session_state:
        defaults = {
            "accepted_policy": True,
            "purpose_detail": "",
            "approval_workflow": "",
            "requires_provider_approval": False,
            "requires_msp_approval": False,
            "provider_reviewed_by": "",
            "provider_reviewed_at": "",
            "msp_reviewed_by": "",
            "msp_reviewed_at": "",
        }
        for col, default in defaults.items():
            if col not in st.session_state.access_requests.columns:
                st.session_state.access_requests[col] = default


def create_token_for_request(request_id: str) -> None:
    req = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_id]
    if req.empty:
        return
    r = req.iloc[0]
    existing = st.session_state.tokens[
        (st.session_state.tokens["dataset_id"].astype(str) == str(r["dataset_id"])) &
        (st.session_state.tokens["consumer_tenant_id"].astype(str) == str(r.get("consumer_tenant_id", ""))) &
        (st.session_state.tokens["status"].astype(str) == "Active")
    ] if len(st.session_state.tokens) else pd.DataFrame()
    if not existing.empty:
        return

    ds = st.session_state.datasets[st.session_state.datasets["dataset_id"].astype(str) == str(r["dataset_id"])]
    classification = str(ds.iloc[0].get("classification", "Internal")) if not ds.empty else "Internal"
    token_days = access_workflow_for_classification(classification)["token_days"]

    token = generate_access_token()
    expiry = (datetime.now() + timedelta(days=token_days)).strftime("%Y-%m-%d")
    new_token = pd.DataFrame([{
        "token": token,
        "dataset_id": r["dataset_id"],
        "dataset_name": r["dataset_name"],
        "consumer_email": r["consumer_email"],
        "consumer_tenant_id": r.get("consumer_tenant_id", ""),
        "permission": "download:masked_sample, view:metadata, view:governed_reference",
        "expiry": expiry,
        "status": "Active",
        "created_at": now_str(),
    }])
    if st.session_state.tokens.empty:
        st.session_state.tokens = new_token.copy()
    else:
        st.session_state.tokens = pd.concat([st.session_state.tokens, new_token], ignore_index=True)

    amount = float(r.get("amount_rm", 0) or 0)
    commission = float(r.get("msp_commission_rm", amount * MSP_COMMISSION_RATE) or 0)
    provider_rev = float(r.get("provider_revenue_rm", amount - commission) or 0)

    idx = st.session_state.datasets[st.session_state.datasets["dataset_id"].astype(str) == str(r["dataset_id"])].index
    if len(idx):
        st.session_state.datasets.loc[idx, "download_count"] = pd.to_numeric(st.session_state.datasets.loc[idx, "download_count"], errors="coerce").fillna(0) + 1
        st.session_state.datasets.loc[idx, "revenue_rm"] = pd.to_numeric(st.session_state.datasets.loc[idx, "revenue_rm"], errors="coerce").fillna(0) + amount
        st.session_state.datasets.loc[idx, "msp_commission_rm"] = pd.to_numeric(st.session_state.datasets.loc[idx, "msp_commission_rm"], errors="coerce").fillna(0) + commission
        st.session_state.datasets.loc[idx, "provider_revenue_rm"] = pd.to_numeric(st.session_state.datasets.loc[idx, "provider_revenue_rm"], errors="coerce").fillna(0) + provider_rev

    if "usage_history" in st.session_state and not st.session_state.usage_history.empty:
        last_idx = st.session_state.usage_history.index[-1]
        st.session_state.usage_history.loc[last_idx, "downloads"] = _int(st.session_state.usage_history.loc[last_idx, "downloads"]) + 1
        st.session_state.usage_history.loc[last_idx, "revenue_rm"] = _num(st.session_state.usage_history.loc[last_idx, "revenue_rm"]) + amount


def create_access_request(dataset_id: str, purpose: str, other_purpose: str, accepted: bool) -> None:
    _ = ensure_enhanced_state()
    user = get_current_user()
    if not accepted:
        st.warning("Please accept the data usage policy before continuing.")
        return
    ds = st.session_state.datasets[st.session_state.datasets["dataset_id"].astype(str) == str(dataset_id)]
    if ds.empty:
        st.error("Dataset not found.")
        return
    row = ds.iloc[0]
    selected_purpose = other_purpose.strip() if purpose == "Other" and other_purpose.strip() else purpose

    existing = st.session_state.access_requests[
        (st.session_state.access_requests["dataset_id"].astype(str) == str(dataset_id)) &
        (st.session_state.access_requests["consumer_tenant_id"].astype(str) == str(user["tenant_id"])) &
        (~st.session_state.access_requests["status"].astype(str).isin(["Rejected", "Cancelled"]))
    ] if "access_requests" in st.session_state and len(st.session_state.access_requests) else pd.DataFrame()
    if not existing.empty:
        st.info("You already have a pending, payment, or approved access record for this dataset. Check My Access Requests or Checkout & Payment.")
        return

    workflow = access_workflow_for_classification(row.get("classification", "Internal"))
    amount = _num(row.get("price_rm", 0))
    commission = round(amount * MSP_COMMISSION_RATE, 2)
    provider_rev = round(amount - commission, 2)
    req_id = generate_id("REQ")

    if workflow["action"] == "Purchase":
        status = "Pending Payment"
        payment_status = "Unpaid"
        reviewed_by = "Auto direct purchase"
        reviewed_at = now_str()
    else:
        status = workflow["status"]
        payment_status = "Pending Approval"
        reviewed_by = ""
        reviewed_at = ""

    new = pd.DataFrame([{
        "request_id": req_id,
        "dataset_id": dataset_id,
        "dataset_name": row["dataset_name"],
        "consumer_email": user["email"],
        "consumer_tenant_id": user["tenant_id"],
        "purpose": selected_purpose,
        "purpose_detail": other_purpose.strip(),
        "status": status,
        "payment_status": payment_status,
        "amount_rm": amount,
        "msp_commission_rate": MSP_COMMISSION_RATE,
        "msp_commission_rm": commission,
        "provider_revenue_rm": provider_rev,
        "accepted_policy": True,
        "approval_workflow": workflow["action"],
        "requires_provider_approval": workflow["requires_provider"],
        "requires_msp_approval": workflow["requires_msp"],
        "provider_reviewed_by": "" if workflow["requires_provider"] else "Auto",
        "provider_reviewed_at": "" if workflow["requires_provider"] else now_str(),
        "msp_reviewed_by": "" if workflow["requires_msp"] else "Auto",
        "msp_reviewed_at": "" if workflow["requires_msp"] else now_str(),
        "created_at": now_str(),
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "rejection_reason": "",
        "rejected_by": "",
        "rejected_at": "",
    }])
    if st.session_state.access_requests.empty:
        st.session_state.access_requests = new.copy()
    else:
        st.session_state.access_requests = pd.concat([st.session_state.access_requests, new], ignore_index=True)

    if workflow["action"] == "Purchase":
        _ = add_log(user["email"], f"Created direct purchase checkout for {row['dataset_name']}", user["tenant_id"])
        st.success("Checkout created. Go to Checkout & Payment to view the billing summary and complete payment before access is granted.")
    else:
        _ = add_log(user["email"], f"Requested access to {row['dataset_name']} through {workflow['action']} workflow", user["tenant_id"])
        st.success("Access request submitted. After approval, complete payment in Checkout & Payment before your access token is generated.")


def render_catalog_card(row, user):
    dataset_id = row["dataset_id"]
    is_msp, is_owner_provider, consumer_token = _access_flags(row, user)
    is_consumer = is_consumer_role(user["role"])
    governance_view = is_msp
    full_view = is_owner_provider or consumer_token
    public_view = not governance_view and not full_view
    title = catalog_title(row)
    provider = tenant_name(row["owner_tenant_id"])
    tags = row.get("tags", "")
    desc = str(row.get("description", ""))
    domain = row.get("domain", CATALOG_DOMAINS.get(row.get("dataset_name", ""), "Other"))
    quality_pct = _quality(row.get("quality_score", 0))
    price = f"RM {_num(row.get('price_rm', 0)):,.2f}"
    classification = str(row.get("classification", "Internal"))
    workflow = access_workflow_for_classification(classification)
    purpose_key = f"purpose_{dataset_id}"
    expanded_now = st.session_state.get(purpose_key) == "Other"

    with st.container(border=True):
        top_left, top_right = st.columns([5, 1])
        status_val = str(row.get("status", ""))
        status_badge = f" <span style='color:#ea580c; font-size:14px; font-weight:bold'>[{status_val}]</span>" if status_val != "Published" else ""

        with top_left:
            st.markdown(f"<div class='catalog-title'>{title}{status_badge}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='catalog-meta'>Provider: {provider} &nbsp;|&nbsp; Format: {row.get('format', '')} &nbsp;|&nbsp; Rows: {_int(row.get('rows', 0)):,} &nbsp;|&nbsp; Quality: {quality_pct}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(tag_pills(tags), unsafe_allow_html=True)
        with top_right:
            st.markdown(
                f"<div style='text-align:right;font-weight:850;color:#047857;font-size:17px;white-space:nowrap;'>{price}</div>",
                unsafe_allow_html=True)
            st.caption(f"{_int(row.get('download_count', 0))} downloads")

        if is_msp:
            expander_title = "View Details"
        elif is_consumer and public_view:
            expander_title = f"View Details & {workflow['action']}"
        else:
            expander_title = "View Details"

        with st.expander(expander_title, expanded=expanded_now):
            c1, c2, c3, c4 = st.columns(4)
            _ = c1.metric("Domain", domain)
            _ = c2.metric("Quality Score", quality_pct)
            _ = c3.metric("Classification", classification)
            _ = c4.metric("Price", price)
            st.markdown(
                f"**Provider:** {provider} &nbsp; | &nbsp; **Format:** {row.get('format', '')} &nbsp; | &nbsp; **Rows/Columns:** {_int(row.get('rows', 0)):,} / {_int(row.get('columns', 0))}")
            st.markdown(tag_pills(tags), unsafe_allow_html=True)
            st.write(desc)

            if governance_view or full_view:
                tabs = st.tabs(["Metadata", "Quality", "Privacy & Masking", "Processing Summary", "Lineage"])
                with tabs[0]:
                    safe_meta = dict(st.session_state.metadata_store.get(dataset_id, {}))
                    st.subheader("Metadata table")
                    metadata_rows = []
                    for key, value in safe_meta.items():
                        if isinstance(value, (dict, list)):
                            display_value = json.dumps(value, ensure_ascii=False)
                        else:
                            display_value = str(value)
                        metadata_rows.append({"Metadata field": key, "Value": display_value})
                    if metadata_rows:
                        st.dataframe(pd.DataFrame(metadata_rows), width="stretch", hide_index=True)
                    else:
                        st.info("No metadata available for this dataset.")
                    with st.expander("Raw metadata JSON"):
                        st.json(safe_meta)
                with tabs[1]:
                    render_dataset_quality_outputs(dataset_id, row.get("dataset_name", ""))
                with tabs[2]:
                    render_privacy_masking_policy_output(dataset_id, row.get("dataset_name", ""))
                with tabs[3]:
                    render_processing_summary_outputs(dataset_id, row.get("dataset_name", ""))
                with tabs[4]:
                    _ = draw_lineage_flow(row.get("dataset_name", "Dataset"))

            if is_consumer and public_view:
                st.divider()
                st.subheader(workflow["action"])
                if workflow["requires_msp"]:
                    st.warning("This request will need provider support and MSP/Governance approval.")
                elif workflow["requires_provider"]:
                    st.info("This request will be reviewed by the provider Data Owner or Provider Administrator.")
                else:
                    st.success("This dataset can be purchased directly after usage terms are accepted.")

                purpose = st.selectbox("Access purpose", ACCESS_PURPOSE_OPTIONS, key=purpose_key)
                if purpose == "Other":
                    other = st.text_area(
                        "Please describe your access purpose",
                        placeholder="Example: I want to use this dataset for customer churn research or academic analytics.",
                        height=110,
                        key=f"other_{dataset_id}",
                    )
                else:
                    other = ""
                with st.form(f"request_{dataset_id}"):
                    st.markdown("**Data Usage Policy:**")
                    for term in CONSUMER_USAGE_TERMS:
                        st.write(f"• {term}")
                    accepted = st.checkbox("I accept the data usage policy.", key=f"accept_{dataset_id}")
                    submitted = st.form_submit_button(workflow["button"], type="primary")
                    if submitted:
                        if purpose == "Other" and not other.strip():
                            st.error("Please describe your access purpose before submitting.")
                        else:
                            _ = create_access_request(dataset_id, purpose, other, accepted)


def page_consumer_requests_for_provider():
    _ = ensure_enhanced_state()
    user = get_current_user()
    _ = show_header("Consumer Requests", "Provider reviews access requests for datasets owned by its own tenant.")
    own_ids = visible_datasets_for_user(user)["dataset_id"].astype(str).tolist()
    req = st.session_state.access_requests[st.session_state.access_requests["dataset_id"].astype(str).isin(own_ids)].copy()
    if req.empty:
        st.info("No consumer requests for your datasets yet.")
        return

    safe_cols = [c for c in [
        "request_id", "dataset_name", "consumer_email", "purpose", "status", "payment_status",
        "amount_rm", "approval_workflow", "requires_provider_approval", "requires_msp_approval",
        "created_at", "provider_reviewed_by", "provider_reviewed_at"
    ] if c in req.columns]
    st.dataframe(req[safe_cols], width="stretch", hide_index=True)

    if not can_approve_provider_request(user["role"]):
        st.info("Your role can view consumer requests but cannot approve or reject them. Provider Administrator or Data Owner approval is required.")
        return

    pending = req[req["status"].isin(["Pending Provider Approval", "Pending Provider/MSP Approval"])]
    if pending.empty:
        st.success("No provider approval action is currently required.")
        return

    for _, request_row in pending.iterrows():
        classification = ""
        ds_row = st.session_state.datasets[st.session_state.datasets["dataset_id"].astype(str) == str(request_row["dataset_id"])]
        if not ds_row.empty:
            classification = str(ds_row.iloc[0].get("classification", ""))
        with st.expander(f"{request_row['request_id']} | {request_row['dataset_name']} | {classification} | {request_row['consumer_email']}"):
            st.write(f"**Purpose:** {request_row['purpose']}")
            st.write(f"**Workflow:** {request_row.get('approval_workflow', '')}")
            c1, c2 = st.columns(2)

            if classification in PROVIDER_APPROVAL_CLASSIFICATIONS:
                approve_label = "Approve access for payment"
            else:
                approve_label = "Support request and send to MSP"

            if c1.button(approve_label, key=f"provider_approve_{request_row['request_id']}"):
                idx = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_row["request_id"]].index
                if classification in PROVIDER_APPROVAL_CLASSIFICATIONS:
                    st.session_state.access_requests.loc[idx, "status"] = "Approved - Pending Payment"
                    st.session_state.access_requests.loc[idx, "payment_status"] = "Unpaid"
                    st.session_state.access_requests.loc[idx, "reviewed_by"] = user["email"]
                    st.session_state.access_requests.loc[idx, "reviewed_at"] = now_str()
                    st.session_state.access_requests.loc[idx, "provider_reviewed_by"] = user["email"]
                    st.session_state.access_requests.loc[idx, "provider_reviewed_at"] = now_str()
                    _ = add_log(user["email"], f"Approved confidential access request {request_row['request_id']} for payment", user["tenant_id"])
                    st.success("Provider approved the request. Consumer must complete payment before token generation.")
                else:
                    st.session_state.access_requests.loc[idx, "status"] = "Provider Supported - Pending MSP Approval"
                    st.session_state.access_requests.loc[idx, "provider_reviewed_by"] = user["email"]
                    st.session_state.access_requests.loc[idx, "provider_reviewed_at"] = now_str()
                    _ = add_log(user["email"], f"Supported restricted access request {request_row['request_id']} for MSP review", user["tenant_id"])
                    st.success("Provider support recorded. MSP/Governance approval is now required.")
                st.rerun()

            provider_rejection_reason = c2.text_area(
                "Reason for rejection",
                key=f"provider_access_rejection_reason_{request_row['request_id']}",
                placeholder="Explain why this access request is rejected.",
            )
            if c2.button("Reject request", key=f"provider_reject_{request_row['request_id']}"):
                if not provider_rejection_reason.strip():
                    st.warning("Please provide a rejection reason before rejecting this access request.")
                else:
                    idx = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_row["request_id"]].index
                    st.session_state.access_requests.loc[idx, "status"] = "Rejected"
                    st.session_state.access_requests.loc[idx, "reviewed_by"] = user["email"]
                    st.session_state.access_requests.loc[idx, "reviewed_at"] = now_str()
                    st.session_state.access_requests.loc[idx, "provider_reviewed_by"] = user["email"]
                    st.session_state.access_requests.loc[idx, "provider_reviewed_at"] = now_str()
                    st.session_state.access_requests.loc[idx, "rejection_reason"] = provider_rejection_reason.strip()
                    st.session_state.access_requests.loc[idx, "rejected_by"] = user["email"]
                    st.session_state.access_requests.loc[idx, "rejected_at"] = now_str()
                    _ = add_log(user["email"], f"Rejected access request {request_row['request_id']}: {provider_rejection_reason.strip()}", user["tenant_id"])
                    st.rerun()


def page_access_request_admin_review():
    _ = ensure_enhanced_state()
    st.subheader("Access Request Approval")
    req = st.session_state.access_requests[
        st.session_state.access_requests["status"].astype(str).isin(["Provider Supported - Pending MSP Approval", "Pending MSP Approval"])
    ].copy()
    if req.empty:
        st.success("No access requests requiring MSP/Governance approval.")
        return

    safe_cols = [c for c in [
        "request_id", "dataset_name", "consumer_email", "purpose", "status", "amount_rm",
        "msp_commission_rm", "provider_revenue_rm", "provider_reviewed_by", "rejection_reason", "created_at"
    ] if c in req.columns]
    st.dataframe(req[safe_cols], width="stretch", hide_index=True)

    for _, request_row in req.iterrows():
        ds_row = st.session_state.datasets[st.session_state.datasets["dataset_id"].astype(str) == str(request_row["dataset_id"])]
        classification = str(ds_row.iloc[0].get("classification", "")) if not ds_row.empty else ""
        with st.expander(f"{request_row['request_id']} | {request_row['dataset_name']} | {classification} | {request_row['consumer_email']}"):
            st.write(f"**Purpose:** {request_row['purpose']}")
            st.write(f"**Provider reviewed by:** {request_row.get('provider_reviewed_by', '')}")
            c1, c2 = st.columns(2)
            if c1.button("Approve access for payment", key=f"msp_access_approve_{request_row['request_id']}"):
                idx = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_row["request_id"]].index
                st.session_state.access_requests.loc[idx, "status"] = "Approved - Pending Payment"
                st.session_state.access_requests.loc[idx, "payment_status"] = "Unpaid"
                st.session_state.access_requests.loc[idx, "reviewed_by"] = get_current_user()["email"]
                st.session_state.access_requests.loc[idx, "reviewed_at"] = now_str()
                st.session_state.access_requests.loc[idx, "msp_reviewed_by"] = get_current_user()["email"]
                st.session_state.access_requests.loc[idx, "msp_reviewed_at"] = now_str()
                _ = add_log(get_current_user()["email"], f"Approved restricted access request {request_row['request_id']} for payment", get_current_user()["tenant_id"])
                st.rerun()
            msp_rejection_reason = c2.text_area(
                "Reason for rejection",
                key=f"msp_access_rejection_reason_{request_row['request_id']}",
                placeholder="Explain why this restricted access request is rejected.",
            )
            if c2.button("Reject access", key=f"msp_access_reject_{request_row['request_id']}"):
                if not msp_rejection_reason.strip():
                    st.warning("Please provide a rejection reason before rejecting this access request.")
                else:
                    idx = st.session_state.access_requests[st.session_state.access_requests["request_id"] == request_row["request_id"]].index
                    st.session_state.access_requests.loc[idx, "status"] = "Rejected"
                    st.session_state.access_requests.loc[idx, "reviewed_by"] = get_current_user()["email"]
                    st.session_state.access_requests.loc[idx, "reviewed_at"] = now_str()
                    st.session_state.access_requests.loc[idx, "msp_reviewed_by"] = get_current_user()["email"]
                    st.session_state.access_requests.loc[idx, "msp_reviewed_at"] = now_str()
                    st.session_state.access_requests.loc[idx, "rejection_reason"] = msp_rejection_reason.strip()
                    st.session_state.access_requests.loc[idx, "rejected_by"] = get_current_user()["email"]
                    st.session_state.access_requests.loc[idx, "rejected_at"] = now_str()
                    _ = add_log(get_current_user()["email"], f"Rejected restricted access request {request_row['request_id']}: {msp_rejection_reason.strip()}", get_current_user()["tenant_id"])
                    st.rerun()


def page_policy_configuration():
    _ = ensure_enhanced_state()
    _ = show_header("Policy Configuration", "Configure sensitivity labels, sensitive data types, approval workflows and platform policy rules.")
    tab1, tab2, tab3, tab4 = st.tabs(["Sensitivity labels", "Sensitive data types", "Policy rules", "Usage terms"])

    with tab1:
        st.subheader("Business sensitivity labels")
        st.caption("These labels determine whether consumers can purchase directly or must go through provider/MSP approval.")
        st.dataframe(st.session_state.sensitivity_catalog, width="stretch", hide_index=True)
        with st.form("add_sensitivity_label_form"):
            c1, c2, c3 = st.columns(3)
            label = c1.text_input("New label")
            severity = c2.selectbox("Severity", ["Low", "Medium", "High", "Critical"])
            workflow = c3.selectbox("Approval workflow", ["Direct purchase", "Provider approval", "Provider + MSP approval", "Provider + Governance approval"])
            policy = st.text_area("Policy guidance")
            if st.form_submit_button("Add label"):
                if label and policy:
                    new_label = pd.DataFrame([{"label": label, "severity": severity, "approval_workflow": workflow, "policy": policy}])
                    st.session_state.sensitivity_catalog = pd.concat([st.session_state.sensitivity_catalog, new_label], ignore_index=True)
                    _ = add_log(get_current_user()["email"], f"Added sensitivity label {label}", get_current_user()["tenant_id"])
                    st.success("Sensitivity label added.")
                    st.rerun()
                else:
                    st.warning("Please enter both label and policy guidance.")

    with tab2:
        st.subheader("Sensitive data type classification rules")
        st.caption("This maps detected sensitive data such as NRIC, phone number, email, billing amount or financial information to default classification and masking controls.")
        edited_types = st.data_editor(st.session_state.sensitive_data_types, width="stretch", hide_index=True, key="sensitive_types_editor")
        if st.button("Save sensitive data type rules"):
            st.session_state.sensitive_data_types = edited_types
            _ = add_log(get_current_user()["email"], "Updated sensitive data type classification rules", get_current_user()["tenant_id"])
            st.success("Sensitive data type rules saved.")
        with st.expander("Add sensitive data type"):
            with st.form("add_sensitive_type_form"):
                c1, c2, c3, c4 = st.columns(4)
                s_type = c1.text_input("Sensitive data type")
                default_class = c2.selectbox("Default classification", CLASSIFICATION_LEVELS, index=2)
                mask = c3.selectbox("Masking policy", ["Preserve", "Partial Mask", "Full Mask", "Preserve / Generalize", "Partial Mask / Aggregate"])
                workflow = c4.selectbox("Approval workflow", ["Direct purchase", "Provider approval", "Provider + MSP approval", "Provider + Governance approval"])
                token_days = st.number_input("Token validity days", min_value=1, max_value=365, value=60)
                policy = st.text_area("Policy")
                if st.form_submit_button("Add sensitive data type"):
                    if s_type and policy:
                        new_type = pd.DataFrame([{
                            "sensitive_type": s_type,
                            "default_classification": default_class,
                            "masking_policy": mask,
                            "approval_workflow": workflow,
                            "token_days": int(token_days),
                            "policy": policy,
                        }])
                        st.session_state.sensitive_data_types = pd.concat([st.session_state.sensitive_data_types, new_type], ignore_index=True)
                        st.success("Sensitive data type added.")
                        st.rerun()
                    else:
                        st.warning("Please enter both sensitive data type and policy.")

    with tab3:
        st.subheader("Platform policy rules")
        st.caption("Tenant eligibility is handled through tenant accounts, while policy rules are based on classification, masking, approval, retention and audit requirements.")
        edited = st.data_editor(st.session_state.policies, width="stretch", hide_index=True, key="policy_editor")
        if st.button("Save policy rules"):
            st.session_state.policies = edited
            _ = add_log(get_current_user()["email"], "Updated platform policy rules", get_current_user()["tenant_id"])
            st.success("Policies saved.")

    with tab4:
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Provider publication terms**")
            for term in PROVIDER_USAGE_TERMS:
                st.write(f"• {term}")
        with c2:
            st.write("**Consumer data usage terms**")
            for term in CONSUMER_USAGE_TERMS:
                st.write(f"• {term}")




def page_msp_dashboard():
    _ = ensure_enhanced_state()
    _ = show_header("MSP Dashboard", "Platform-level governance, monetization and catalog health overview.")
    ds = st.session_state.datasets.copy()
    tenants = st.session_state.tenants.copy()
    req = st.session_state.access_requests.copy()
    usage = st.session_state.usage_history.copy()

    gross_revenue = _num(ds.get("revenue_rm", pd.Series([0])).sum() if len(ds) else 0)
    msp_commission = _num(ds.get("msp_commission_rm", pd.Series([0])).sum() if len(ds) else 0)
    provider_revenue = _num(ds.get("provider_revenue_rm", pd.Series([0])).sum() if len(ds) else 0)
    trend_revenue = _num(usage.get("revenue_rm", pd.Series([0])).sum() if len(usage) else 0)

    pending_review = int(ds["status"].isin(["Submitted", "Privacy Review", "MSP Review"]).sum()) if len(ds) else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    _ = c1.metric("Data Providers", int((tenants["tenant_type"] == "Data Provider").sum()))
    _ = c2.metric("Data Consumers", int((tenants["tenant_type"] == "Data Consumer").sum()))
    _ = c3.metric("Published Datasets", int((ds["status"] == "Published").sum()) if len(ds) else 0)
    _ = c4.metric("Pending Review", pending_review)
    _ = c5.metric("Data Provider Revenue", f"RM {provider_revenue:,.2f}")
    _ = c6.metric("MSP Revenue", f"RM {msp_commission:,.2f}")

    left, right = st.columns(2)
    with left:
        st.subheader("Monthly platform activity")
        if not usage.empty:
            st.line_chart(usage.set_index("month")[["downloads", "requests"]])
        st.subheader("Classification distribution")
        if len(ds):
            st.bar_chart(ds["classification"].value_counts())
        else:
            st.info("No datasets yet.")
    with right:
        st.subheader("Revenue trend")
        if not usage.empty:
            st.line_chart(usage.set_index("month")[["revenue_rm"]])
        st.subheader("Access workflow status")
        if len(req):
            st.bar_chart(req["status"].value_counts())
        else:
            st.info("No access requests yet.")

    st.subheader("Top catalog assets")
    if len(ds):
        cols = ["catalog_title", "dataset_name", "status", "classification", "quality_score", "download_count", "price_rm", "revenue_rm", "msp_commission_rm", "owner_tenant_id"]
        top = ds[[c for c in cols if c in ds.columns]].copy()
        if "owner_tenant_id" in top.columns:
            top["provider"] = top["owner_tenant_id"].apply(tenant_name)
            top = top.drop(columns=["owner_tenant_id"])
        st.dataframe(top.sort_values("download_count", ascending=False) if "download_count" in top.columns else top, width="stretch", hide_index=True)


# =============================================================================
# Storage-layer and navigation
# =============================================================================
def _provider_workspace_row_for_user(user: Dict) -> Optional[pd.Series]:
    _ = ensure_enhanced_state()
    if "workspaces" not in st.session_state:
        return None
    ws = st.session_state.workspaces[st.session_state.workspaces["tenant_id"].astype(str) == str(user["tenant_id"])]
    if ws.empty:
        return None
    return ws.iloc[0]


def page_managed_fabric_storage():
    _ = ensure_enhanced_state()
    user = get_current_user()
    is_msp = is_msp_role(user["role"])
    _ = show_header(
        "Managed Fabric Storage Layer",
        "Optional MSP-managed Microsoft Fabric workspace and Lakehouse storage for provider dataset onboarding, processing and catalog publication."
    )

    st.info(
        "Use this storage layer when a provider needs Credence/MSP to host raw, cleaned, masked and report outputs in Microsoft Fabric. "
        "If the provider already stores data in its own database, ADLS, S3, API, Fabric workspace or another governed platform, the provider may skip provisioning and register the external source directly in the Data Catalog."
    )

    if is_msp:
        st.subheader("Provision workspace for data provider")
        providers = st.session_state.tenants[st.session_state.tenants["tenant_type"] == "Data Provider"].copy()
        if providers.empty:
            st.warning("No data provider tenant available.")
        else:
            provider_options = {f"{r['tenant_name']} ({r['tenant_id']})": r for _, r in providers.iterrows()}
            selected = st.selectbox("Provider tenant", list(provider_options.keys()), key="msp_workspace_provider_select")
            provider = provider_options[selected]
            default_ws_name = f"{provider['tenant_name']} Monetization Workspace"
            platform = "Microsoft Fabric"
            c1, c2 = st.columns(2)
            with c1:
                ws_name = st.text_input("Workspace name", value=default_ws_name, key="msp_workspace_name")
                lakehouse = st.text_input("Lakehouse", value=FABRIC_LAKEHOUSE_NAME, key="msp_lakehouse_name")
            with c2:
                raw_folder = st.text_input("Raw folder", value=f"Files/raw/{provider['tenant_id'].lower().replace('t-', '')}", key="msp_raw_folder")
                fabric_url = st.text_input("Fabric workspace / lakehouse URL", value=FABRIC_PORTAL_LAKEHOUSE_URL, key="msp_workspace_url")
            if st.button("Provision Workspace", type="primary"):
                tid = str(provider["tenant_id"])
                ws_id = f"WS-{tid.replace('T-', '').replace('-', '')}"
                new_row = pd.DataFrame([{
                    "workspace_id": ws_id,
                    "tenant_id": tid,
                    "tenant_name": provider["tenant_name"],
                    "workspace_name": ws_name,
                    "lakehouse": lakehouse,
                    "platform": platform,
                    "status": "Provisioned",
                    "fabric_url": fabric_url,
                    "raw_folder": raw_folder,
                    "cleaned_output": "Files/processed/cleaned",
                    "masked_output": "Files/processed/masked",
                    "quality_report": "Files/processed/reports/quality",
                    "privacy_report": "Files/processed/reports/privacy"
                }])
                if "workspaces" not in st.session_state or st.session_state.workspaces.empty:
                    st.session_state.workspaces = new_row.copy()
                else:
                    existing_idx = st.session_state.workspaces[st.session_state.workspaces["tenant_id"].astype(str) == tid].index
                    if len(existing_idx):
                        for col in new_row.columns:
                            if col not in st.session_state.workspaces.columns:
                                st.session_state.workspaces[col] = ""
                            st.session_state.workspaces.loc[existing_idx, col] = new_row.iloc[0][col]
                    else:
                        for col in new_row.columns:
                            if col not in st.session_state.workspaces.columns:
                                st.session_state.workspaces[col] = ""
                        st.session_state.workspaces = pd.concat([st.session_state.workspaces, new_row], ignore_index=True)
                _ = add_log(user["email"], f"Provisioned/updated Fabric storage workspace for {provider['tenant_name']}", user["tenant_id"])
                st.success("Workspace provisioned successfully. The status was updated automatically to Provisioned.")

        st.subheader("All provider storage environments")
        if "workspaces" in st.session_state and not st.session_state.workspaces.empty:
            st.dataframe(st.session_state.workspaces, width="stretch", hide_index=True)
        else:
            st.info("No workspace records yet.")
        return

    st.subheader("Your storage environment")
    ws = _provider_workspace_row_for_user(user)
    if ws is None:
        st.warning("No managed Fabric workspace is provisioned for this provider yet.")
        st.write("You can still register datasets from your own external platform in Register Dataset. Ask MSP to provision a Fabric workspace only if you want managed storage and processing.")
        return

    c1, c2 = st.columns(2)
    _ = c1.metric("Storage platform", str(ws.get("platform", "Microsoft Fabric")))
    _ = c2.metric("Status", str(ws.get("status", "Provisioned")))

    rows = pd.DataFrame([{
        "Workspace": ws.get("workspace_name", ""),

        "Lakehouse": ws.get("lakehouse", ""),
        "Raw folder": ws.get("raw_folder", FABRIC_RELATIVE_FOLDER),
        "Cleaned output": ws.get("cleaned_output", "Files/processed/cleaned"),
        "Masked output": ws.get("masked_output", "Files/processed/masked"),
        "Quality report": ws.get("quality_report", "Files/processed/reports/quality"),
        "Privacy report": ws.get("privacy_report", "Files/processed/reports/privacy"),
    }])
    st.dataframe(rows, width="stretch", hide_index=True)
    link = str(ws.get("fabric_url", ""))
    if link.startswith("https://"):
        st.link_button("Open managed Fabric Lakehouse", link)

    st.markdown(
        """
        <div class='small-note'><b>How this is used in the prototype:</b><br>
        1. If a provider uploads a file in Streamlit, the upload represents a dataset being ingested into the MSP-managed Fabric Lakehouse.<br>
        2. Fabric stores the raw file, while the Streamlit prototype runs metadata discovery, quality scoring, privacy scanning and masking.<br>
        3. The Streamlit catalog records the metadata and governance status, while Purview-style catalog and lineage references are represented in the platform.<br>
        4. If the provider already has its own database, API, S3, ADLS or Fabric workspace, they can skip this and register the external source directly.
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_provider_dashboard():
    _ = ensure_enhanced_state()
    user = get_current_user()
    _ = show_header("Provider Dashboard",
                    "Provider analytics for catalog publication, access requests, downloads and revenue.")

    ds = st.session_state.datasets[
        st.session_state.datasets["owner_tenant_id"].astype(str) == str(user["tenant_id"])].copy()
    req = st.session_state.access_requests[
        st.session_state.access_requests["dataset_id"].isin(ds["dataset_id"])] if len(ds) and len(
        st.session_state.access_requests) else pd.DataFrame()
    usage = st.session_state.usage_history.copy() if "usage_history" in st.session_state else pd.DataFrame()
    gross_revenue = _num(ds.get("revenue_rm", pd.Series([0])).sum() if len(ds) else 0)
    provider_revenue = _num(ds.get("provider_revenue_rm", pd.Series([0])).sum() if len(ds) else 0)

    st.subheader("Provider analytics")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    _ = c1.metric("My datasets", len(ds))
    _ = c2.metric("Published", int((ds["status"] == "Published").sum()) if len(ds) else 0)

    pending_dataset_review = int(
        ds["status"].astype(str).isin(["MSP Review", "Submitted", "Privacy Review"]).sum()) if len(ds) else 0
    _ = c3.metric("Pending dataset review", pending_dataset_review)

    pending_access_requests = int(
        req["status"].astype(str).isin(["Pending Provider Approval", "Pending Provider/MSP Approval"]).sum()) if len(
        req) else 0
    _ = c4.metric("Pending access requests", pending_access_requests)

    _ = c5.metric("Downloads",
                  int(pd.to_numeric(ds.get("download_count", pd.Series([0])), errors="coerce").fillna(0).sum()) if len(
                      ds) else 0)
    _ = c6.metric("Provider Revenue", f"RM {provider_revenue:,.2f}")

    left, right = st.columns(2)
    with left:
        st.subheader("Dataset status")
        if len(ds):
            st.bar_chart(ds["status"].value_counts())
        else:
            st.info("No datasets registered yet.")

        st.subheader("Dataset popularity")
        if len(ds):
            title_col = "catalog_title" if "catalog_title" in ds.columns else "dataset_name"
            pop = ds[[title_col, "download_count"]].copy()
            pop["download_count"] = pd.to_numeric(pop["download_count"], errors="coerce").fillna(0)
            st.bar_chart(pop.set_index(title_col)["download_count"])
    with right:
        st.subheader("Monthly usage trend")
        if not usage.empty:
            st.line_chart(usage.set_index("month")[["downloads", "requests"]])
        else:
            st.info("No usage trend data available yet.")

        st.subheader("Revenue trend")
        if not usage.empty and "revenue_rm" in usage.columns:
            st.line_chart(usage.set_index("month")[["revenue_rm"]])
            st.caption(
                f"Gross demo revenue represented in trend: RM {_num(usage['revenue_rm'].sum()):,.2f}. Current provider gross revenue: RM {gross_revenue:,.2f}.")

def page_tenant_user_management():
    _ = ensure_enhanced_state()
    _ = show_header("Tenant & User Management", "MSP-level provisioning for tenants, users and provider governance settings.")

    st.subheader("Tenants")
    tenant_view = st.session_state.tenants.copy()
    tenant_display_cols = [c for c in tenant_view.columns if c != "requires_msp_approval"]
    st.dataframe(tenant_view[tenant_display_cols], width="stretch", hide_index=True)

    st.subheader("Provider approval settings")
    providers = st.session_state.tenants[st.session_state.tenants["tenant_type"] == "Data Provider"].copy()
    st.info("Default rule: when a data provider registers a dataset using their own account, the dataset requires MSP approval. MSP may untick this for trusted providers.")
    if providers.empty:
        st.warning("No provider tenants available.")
    else:
        edited_providers = st.data_editor(
            providers[["tenant_id", "tenant_name", "status", "requires_msp_approval"]],
            width="stretch",
            hide_index=True,
            column_config={"requires_msp_approval": st.column_config.CheckboxColumn("Require MSP approval")},
            key="provider_approval_inside_tenant_management",
        )
        if st.button("Save provider approval settings"):
            for _, row in edited_providers.iterrows():
                idx = st.session_state.tenants[st.session_state.tenants["tenant_id"] == row["tenant_id"]].index
                if len(idx):
                    st.session_state.tenants.loc[idx, "requires_msp_approval"] = bool(row["requires_msp_approval"])
            _ = add_log(get_current_user()["email"], "Updated provider approval settings from Tenant & User Management", get_current_user()["tenant_id"])
            st.success("Provider approval settings saved.")

    st.subheader("Users")
    show_users = st.session_state.users.drop(columns=["password_hash"])
    st.dataframe(show_users, width="stretch", hide_index=True)

    with st.expander("Provision new tenant and user"):
        c1, c2 = st.columns(2)
        with c1:
            tenant_name_input = st.text_input("New tenant name", key="new_tenant_name")
            tenant_type = st.selectbox("Tenant type", TENANT_TYPES, key="new_tenant_type")
            approval = True if tenant_type == "Data Provider" else False
            st.caption("Provider approval can be adjusted in Provider approval settings above after creation.")
        with c2:
            name = st.text_input("User full name", key="new_user_name")
            email = st.text_input("User email", key="new_user_email")
            available_roles = roles_for_tenant_type(tenant_type)
            role = st.selectbox("User role", available_roles, key="new_user_role")
            password = st.text_input("Temporary password", value="password123", type="password", key="new_user_password")
        if st.button("Provision tenant and user", key="provision_tenant_user"):
            if not tenant_name_input or not name or not email or not password:
                st.warning("Please fill in all required fields.")
                return
            tenant_id = generate_id("T")
            new_tenant = pd.DataFrame([{"tenant_id": tenant_id, "tenant_name": tenant_name_input, "tenant_type": tenant_type, "requires_msp_approval": approval, "status": "Active", "created_at": today_str()}])
            new_user = pd.DataFrame([{"email": email.lower(), "name": name, "password_hash": hash_password(password), "role": role, "tenant_id": tenant_id, "status": "Active"}])
            st.session_state.tenants = pd.concat([st.session_state.tenants, new_tenant], ignore_index=True)
            st.session_state.users = pd.concat([st.session_state.users, new_user], ignore_index=True)
            _ = add_log(get_current_user()["email"], f"Provisioned tenant {tenant_name_input} and user {email}", get_current_user()["tenant_id"])
            st.success("Tenant and user provisioned.")
            st.rerun()


def page_profile_settings():
    user = get_current_user()
    _ = show_header("Profile Settings", "Manage your profile and password.")
    st.subheader("Profile")
    c1, c2 = st.columns(2)
    c1.write(f"**Name:** {user['name']}")
    c1.write(f"**Email:** {user['email']}")
    c2.write(f"**Role:** {user['role']}")
    c2.write(f"**Tenant:** {tenant_name(user['tenant_id'])}")

    st.subheader("Change password")
    with st.form("change_password_form"):
        current_pw = st.text_input("Current password", type="password")
        new_pw = st.text_input("New password", type="password")
        confirm_pw = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update password", type="primary")
    if submitted:
        user_idx = st.session_state.users[st.session_state.users["email"].astype(str).str.lower() == str(user["email"]).lower()].index
        if not len(user_idx):
            st.error("User record not found.")
            return
        stored_hash = st.session_state.users.loc[user_idx[0], "password_hash"]
        if not verify_password(current_pw, stored_hash):
            st.error("Current password is incorrect.")
        elif len(new_pw) < 6:
            st.error("New password should be at least 6 characters.")
        elif new_pw != confirm_pw:
            st.error("New password and confirmation do not match.")
        else:
            st.session_state.users.loc[user_idx[0], "password_hash"] = hash_password(new_pw)
            _ = add_log(user["email"], "Changed account password", user["tenant_id"])
            st.success("Password updated successfully.")


def _apply_demo_pii_defaults():
    _ = ensure_enhanced_state()
    if "datasets" not in st.session_state or st.session_state.datasets.empty:
        return
    if "pii_declaration" not in st.session_state.datasets.columns:
        st.session_state.datasets["pii_declaration"] = "Unsure"
    defaults = {"customer.csv": "Yes", "billing.csv": "Unsure", "service.csv": "Unsure"}
    for fname, pii in defaults.items():
        mask = st.session_state.datasets["dataset_name"].astype(str).eq(fname)
        if mask.any():
            st.session_state.datasets.loc[mask, "pii_declaration"] = pii


def sidebar_navigation() -> str:
    user = get_current_user()
    with st.sidebar:
        try:
            st.image("Credence_full_logo.png", width=180)
        except:
            pass
        st.markdown(f"### {APP_NAME}")
        st.write(f"**User:** {user['name']}")
        st.write(f"**Role:** {user['role']}")
        st.write(f"**Tenant:** {tenant_name(user['tenant_id'])}")
        st.markdown(
            f"<div class='small-note'>{role_quick_guide(user['role'])}</div>",
            unsafe_allow_html=True,
        )
        st.divider()
        role = user["role"]
        if role == "MSP Administrator":
            pages = ["MSP Dashboard", "Tenant & User Management", "Managed Fabric Storage", "Data Catalog",
                     "Dataset Approval Queue", "Dataset Review / Audit", "Policy Configuration", "Lineage & Glossary",
                     "Governance Monitoring", "Feedback", "Audit Log", "Profile Settings"]

        elif role == "Governance Administrator":
            pages = ["Governance Dashboard", "Data Catalog", "Dataset Approval Queue", "Dataset Review / Audit",
                     "Classification & Policy Review", "Policy Configuration", "Lineage & Glossary",
                     "Governance Monitoring", "Audit Log", "Profile Settings"]

        elif role == "Marketplace Administrator":
            pages = ["MSP Dashboard", "Data Catalog", "Dataset Approval Queue", "Feedback", "Audit Log", "Profile Settings"]

        elif role == "Catalog Administrator":
            pages = ["Governance Dashboard", "Data Catalog", "Classification & Policy Review", "Lineage & Glossary",
                 "Audit Log", "Profile Settings"]

        elif role == "Platform Operator":
            pages = ["MSP Dashboard", "Managed Fabric Storage", "Data Catalog", "Governance Monitoring", "Audit Log",
                 "Profile Settings"]

        elif role in ["Provider Administrator", "Data Owner"]:
            pages = ["Provider Dashboard", "Managed Fabric Storage", "Data Catalog", "Register Dataset", "My Datasets",
                 "Consumer Requests", "Account Management", "Feedback", "Profile Settings"]

        elif role == "Data Steward":
            pages = ["Provider Dashboard", "Managed Fabric Storage", "Data Catalog", "My Datasets", "Lineage & Glossary",
                 "Feedback", "Profile Settings"]

        elif role == "Data Contributor":
            pages = ["Provider Dashboard", "Managed Fabric Storage", "Data Catalog", "Register Dataset", "My Datasets",
                 "Feedback", "Profile Settings"]

        elif is_consumer_role(role):
            pages = ["Consumer Dashboard", "Data Catalog", "My Access Requests", "Checkout & Payment",
                 "My Tokens & Downloads", "Feedback", "Profile Settings"]

        else:
            pages = ["Data Catalog", "Profile Settings"]

        # --- MODIFIED: Enforce routing using session state index mapping ---
        if "current_page" not in st.session_state or st.session_state.current_page not in pages:
            st.session_state.current_page = pages[0]

        try:
            default_index = pages.index(st.session_state.current_page)
        except ValueError:
            default_index = 0
            st.session_state.current_page = pages[0]

        page = st.radio("Navigation", pages, index=default_index)
        st.session_state.current_page = page
        # --- END MODIFIED ---

        st.divider()
        if st.button("Log out"):
            _ = add_log(user["email"], "Logged out", user["tenant_id"])
            st.session_state.current_user = None
            st.session_state.current_page = None
            st.rerun()
    return page

def main():
    handle_stripe_checkout_return()
    if get_current_user() is None:
        _ = login_screen()
        return
    _ = ensure_enhanced_state()
    complete_pending_stripe_return_after_login()
    _ = _apply_demo_pii_defaults()
    page = sidebar_navigation()
    if page == "MSP Dashboard":
        _ = page_msp_dashboard()
    elif page == "Tenant & User Management":
        _ = page_tenant_user_management() if can_manage_tenants(get_current_user()["role"]) else st.error("You do not have permission to manage tenants and users.")
    elif page == "Managed Fabric Storage":
        _ = page_managed_fabric_storage()
    elif page == "Dataset Approval Queue":
        if can_review_dataset(get_current_user()["role"]):
            _ = page_dataset_approval_queue()
        if can_review_dataset(get_current_user()["role"]) or can_manage_marketplace(get_current_user()["role"]):
            _ = page_access_request_admin_review()
    elif page == "Data Catalog":
        _ = page_data_catalog()
    elif page == "Governance Monitoring":
        _ = page_governance_monitoring()
    elif page == "Policy Configuration":
        _ = page_policy_configuration() if can_manage_policies(get_current_user()["role"]) else st.error("You do not have permission to configure governance policies.")
    elif page == "Audit Log":
        _ = page_audit_log()
    elif page == "Governance Dashboard":
        _ = page_governance_dashboard()
    elif page == "Dataset Review / Audit":
        _ = page_privacy_review_queue()
    elif page == "Classification & Policy Review":
        _ = page_classification_policy_review()
    elif page == "Provider Dashboard":
        _ = page_provider_dashboard()
    elif page == "Register Dataset":
        _ = page_register_dataset() if can_register_dataset(get_current_user()["role"]) else st.error("Your role can view datasets but cannot register new datasets.")
    elif page == "My Datasets":
        _ = page_my_datasets()
    elif page == "Consumer Requests":
        _ = page_consumer_requests_for_provider()
    elif page == "Consumer Dashboard":
        _ = page_consumer_dashboard()
    elif page == "My Access Requests":
        _ = page_my_access_requests()
    elif page == "Checkout & Payment":
        _ = page_checkout_payment()
    elif page == "My Tokens & Downloads":
        _ = page_my_tokens_downloads()
    elif page == "Lineage & Glossary":
        _ = page_lineage_glossary()
    elif page == "Account Management":
        _ = page_account_management()
    elif page == "Feedback":
        _ = page_feedback()
    elif page == "Profile Settings":
        _ = page_profile_settings()


def ensure_enhanced_state() -> None:
    _ = ensure_catalog_support_state()
    ensure_review_tracking_columns()
    if "processing_reports" not in st.session_state or not isinstance(st.session_state.processing_reports, dict):
        st.session_state.processing_reports = load_processing_report_tables()
    if "payment_transactions" not in st.session_state:
        st.session_state.payment_transactions = pd.DataFrame(columns=[
            "transaction_id", "request_id", "dataset_id", "dataset_name", "consumer_email",
            "payment_method", "gateway", "amount_rm", "msp_commission_rm", "provider_revenue_rm",
            "gateway_status", "authorization_code", "paid_at",
        ])
    if "datasets" in st.session_state and len(st.session_state.datasets):
        for _, ds_row in st.session_state.datasets.iterrows():
            if str(ds_row.get("dataset_name", "")).lower() in DEMO_MASKED_DATASET_FILES:
                apply_demo_processing_outputs(str(ds_row["dataset_id"]), str(ds_row["dataset_name"]))

    # Keep dataset domains aligned with the three telecom demo datasets.
    demo_domain_map = {
        "customer.csv": "Customer",
        "billing.csv": "Billing",
        "service.csv": "Service",
    }
    if "datasets" in st.session_state and len(st.session_state.datasets):
        if "domain" not in st.session_state.datasets.columns:
            st.session_state.datasets["domain"] = "Other"
        for fname, domain in demo_domain_map.items():
            mask = st.session_state.datasets["dataset_name"].astype(str).str.lower().eq(fname)
            if mask.any():
                st.session_state.datasets.loc[mask, "domain"] = domain

    if "glossary_terms" not in st.session_state or st.session_state.glossary_terms.empty:
        st.session_state.glossary_terms = pd.DataFrame([
            {"term": "Customer", "domain": "Customer", "definition": "Subscriber or organization consuming telecommunication services.", "owner": "TM One Data Steward"},
            {"term": "Customer Segment", "domain": "Customer", "definition": "Business grouping used to analyze subscriber profiles, plans and behaviour.", "owner": "TM One Data Steward"},
            {"term": "Billing Account", "domain": "Billing", "definition": "Account used to manage invoicing and payment transactions for a customer.", "owner": "TM One Data Steward"},
            {"term": "Revenue", "domain": "Billing", "definition": "Income generated from customer subscriptions, billing and service usage.", "owner": "TM One Data Steward"},
            {"term": "Service Subscription", "domain": "Service", "definition": "Active telecommunication service subscribed by a customer.", "owner": "TM One Data Steward"},
            {"term": "Network Performance", "domain": "Service", "definition": "Measurement of service quality such as latency, outage, availability and SLA performance.", "owner": "TM One Data Steward"},
            {"term": "SLA Tier", "domain": "Service", "definition": "Service level commitment used to compare support priority and service quality expectations.", "owner": "TM One Data Steward"},
            {"term": "Governed Access", "domain": "Governance", "definition": "Controlled dataset access using approval workflows, accepted usage terms, payment simulation and access tokens.", "owner": "Credence MSP Governance"},
        ])

    if "data_products" not in st.session_state or st.session_state.data_products.empty:
        st.session_state.data_products = pd.DataFrame([
            {
                "product_name": "Telecommunication Customer Analytics Package",
                "domains": "Customer, Billing, Service",
                "provider": "TM One",
                "datasets": "customer.csv, billing.csv, service.csv",
                "price_rm": 260.0,
                "status": "Published",
                "use_case": "Customer segmentation, revenue analysis and service quality research.",
            }
        ])

    current_domains = list(st.session_state.get("business_domains", []))
    st.session_state.business_domains = clean_label_list(current_domains + ["Customer", "Billing", "Service", "Governance"] + DOMAIN_OPTIONS)



if __name__ == "__main__":
    _ = main()
