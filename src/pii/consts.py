from __future__ import annotations

# Configuration & Constants

CONTEXT_WINDOW = 40

# Keywords for context boosting
KEYWORDS = {
    'SSN': {'ssn', 'social security', 'soc sec'},
    'PHONE_NUMBER': {'phone', 'tel', 'mobile', 'cell', 'fax', 'contact'},
    'BIRTHDATE': {'dob', 'date of birth', 'born', 'birthdate', 'birth'},
    'ACCOUNT_NUMBER': {'account', 'acct', 'a/c', 'iban', 'routing', 'swift', 'bank'},
    'ADDRESS': {
        'address', 'addr', 'ship to', 'billing', 'street', 'residence', 'live at', 'located at',
        'zip', 'zip code', 'zipcode', 'postal', 'postcode'
    }
}

# Zip/postal context keywords for validating standalone postal codes
ZIP_CONTEXT_KEYWORDS = {'zip', 'zip code', 'zipcode', 'postal', 'postcode'}

# Negative context keywords - if these appear near a match, suppress detection
NEGATIVE_CONTEXT = {
    'PHONE_NUMBER': {
        'id', 'id:', 'id card', 'identification', 'passport', 'imei', 'driver',
        'license', 'account', 'acct', 'cc', 'credit card', 'card:', 'card ending',
        'payment', 'policy', 'record', 'verification', 'tax', 'iban', 'masked',
        'inv-', 'order-', 'bill-', 'trans-', 'file', 'reference', 'ref', 'ref-',
        'doc', 'doc no', 'docnum', 'document', 'form', 'form id', 'incident',
        'food item', 'number:', 'authenticated', 'verified', 'ids'
    },
    'SSN': {
        'passport', 'passport number', 'driver', 'license', 'id card', 'id number',
        'identification', 'national id', 'employee id', 'student id', 'member id',
        'tax', 'tax number', 'taxnum', 'tax id', 'tin'
    },
    'ACCOUNT_NUMBER': {
        'credit card', 'card:', 'card number', 'cc:', 'debit card', 'visa', 'mastercard',
        'amex', 'passport', 'passport number', 'phone', 'tel', 'mobile', 'fax',
        'driver', 'license', 'id card', 'id number', 'ssn', 'social security',
        'id', 'id:', 'ref', 'ref-', 'doc', 'doc no', 'docnum', 'document', 'form', 'form id',
        'policy', 'reference', 'report id', 'imei', 'vin', 'invoice', 'payment',
        'transaction', 'order'
    }
}

# Regex Patterns
PATTERNS = {
    'SSN': [
        r'\b\d{3}-\d{2}-\d{4}\b',
        r'\b\d{3} \d{2} \d{4}\b',
        r'\b\d{3}\.\d{2}\.\d{4}\b',  # Dot-separated format
        r'\b\d{9}\b'
    ],
    'PHONE_NUMBER': [
        # US/Canada style: +1-555-123-4567, (555) 123-4567
        r'(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?:[-. ]?\d{1,5})?',
        # International 4-group: +852-9448-6764, +44 20 7946 0958
        r'\+\d{1,4}[-. ]?\d{2,4}[-. ]?\d{3,4}[-. ]?\d{3,4}(?:[-. ]?\d{1,4})?',
        # International 3-group: 81-99521-4238, +81-99521-4238
        r'\+?\d{1,4}[-. ]\d{4,6}[-. ]\d{4}',
        # 4-6 digit area + 5-6 digit local: 03327-050327, 09571-68738, 06863 87625
        r'\b\d{4,6}[-. ]\d{5,6}\b'
    ],
    'DATE': [
        r'\b\d{4}-\d{2}-\d{2}\b',  # YYYY-MM-DD
        r'\b\d{1,2}/\d{1,2}/\d{4}\b',  # DD/MM/YYYY or MM/DD/YYYY
        r'\b[A-Z][a-z]{2,8} \d{1,2},? \d{4}\b'  # Month DD, YYYY
    ],
    'ACCOUNT_NUMBER': [
        r'\b\d{10,17}\b',  # Generic long digit run (10+ to avoid SSN confusion)
        r'\b[A-Z]{2}\d{10,}\b'  # IBAN-like: 2 letters + 10+ digits
    ],
    'ADDRESS': [
        # Heuristic: number + street words + suffix
        # Suffixes
        r'\b\d{1,5}\s+[A-Za-z0-9 .]+\s+(?:St|Street|Rd|Road|Ave|Avenue|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Place|Pl|Circle|Cir)\b(?:.{0,20}(?:Apt|Unit|#|Suite|Ste|Floor|Fl)\s*\w+)?(?:.{0,30}(?:\d{5}(?:-\d{4})?)?)?',
        # ZIP/postal code (validated by zip context in logic)
        r'\b\d{5}(?:-\d{4})?\b',
        # 4-digit postal code (validated by zip context in logic)
        r'\b\d{4}\b'
    ],
    'EMAIL': [
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
    ]
}

# Base Scores
SCORES = {
    'PERSON': 0.80,
    'LOCATION': 0.75,
    'SSN': 0.95,
    'PHONE_NUMBER': 0.85,
    'DATE': 0.75,
    'BIRTHDATE': 0.75,
    'ACCOUNT_NUMBER': 0.80,  # 0.60 if no context
    'ADDRESS': 0.70,
    'EMAIL': 0.90,
    # Piiranha types
    'CREDIT_CARD_NUMBER': 0.95,
    'DRIVERS_LICENSE': 0.90,
    'ID_CARD': 0.90,
    'TAX_NUMBER': 0.90,
    'USERNAME': 0.85,
    'PASSWORD': 0.95,
    'ZIPCODE': 0.75
}

# Piiranha model configuration
PIIRANHA_MODEL_NAME = "iiiorg/piiranha-v1-detect-personal-information"
PIIRANHA_MAX_TOKENS = 512  # model's actual max_position_embeddings
PIIRANHA_CHUNK_SIZE = 450  # tokens per chunk (leaving room for special tokens)
PIIRANHA_OVERLAP = 50  # overlap tokens between chunks

# Map Piiranha labels to our entity types
PIIRANHA_LABEL_MAP = {
    "GIVENNAME": "PERSON",
    "SURNAME": "PERSON",
    "STREET": "ADDRESS",
    "CITY": "ADDRESS",
    "BUILDINGNUM": "ADDRESS",
    "ZIPCODE": "ZIPCODE",
    "SOCIALNUM": "SSN",
    "TELEPHONENUM": "PHONE_NUMBER",
    "DATEOFBIRTH": "BIRTHDATE",
    "EMAIL": "EMAIL",
    "ACCOUNTNUM": "ACCOUNT_NUMBER",
    "CREDITCARDNUMBER": "CREDIT_CARD_NUMBER",
    "DRIVERLICENSENUM": "DRIVERS_LICENSE",
    "IDCARDNUM": "ID_CARD",
    "TAXNUM": "TAX_NUMBER",
    "USERNAME": "USERNAME",
    "PASSWORD": "PASSWORD",
}

# Evaluation constants
ADDRESS_GROUP_MAX_GAP = 30
ADDRESS_GROUP_MAX_SPAN = 120
