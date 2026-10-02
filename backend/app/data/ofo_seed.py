"""
Seed data for SA OFO (Organising Framework for Occupations) taxonomy.

Based on OFO major groups aligned with:
- SA OiHD (Occupations in High Demand) 2024 list
- ICT and engineering occupations relevant to CPUT programmes

OFO codes follow the 8-digit structure: Major(2)-SubMajor(2)-Minor(2)-Unit(2)
"""
from __future__ import annotations

from typing import Dict, List, Optional

# OFO Major Groups relevant to ICT
OFO_MAJOR_GROUPS: List[Dict] = [
    {
        "ofo_code": "20000000",
        "preferred_label": "Professionals",
        "description": "Professional occupations in ICT, engineering, and related fields.",
        "skill_type": "occupation_group",
        "top_concept": True,
    },
    {
        "ofo_code": "10000000",
        "preferred_label": "Managers",
        "description": "Managerial occupations including ICT project and programme management.",
        "skill_type": "occupation_group",
        "top_concept": True,
    },
]

# ICT-relevant sub-major groups
OFO_SUB_GROUPS: List[Dict] = [
    {
        "ofo_code": "25000000",
        "preferred_label": "ICT Professionals",
        "description": "Information and communications technology professionals.",
        "skill_type": "occupation_group",
        "parent_code": "20000000",
    },
    {
        "ofo_code": "21000000",
        "preferred_label": "Science and Engineering Professionals",
        "description": "Physical sciences, engineering, and related professionals.",
        "skill_type": "occupation_group",
        "parent_code": "20000000",
    },
]

# ICT unit group occupations (OFO minor/unit groups)
OFO_OCCUPATIONS: List[Dict] = [
    {
        "ofo_code": "25110101",
        "preferred_label": "Systems Analyst",
        "description": "Analyses, designs, and specifies information systems to meet business requirements.",
        "parent_code": "25000000",
        "skills": [
            "systems analysis", "requirements gathering", "business process modelling",
            "software development lifecycle", "UML", "stakeholder management",
            "technical documentation", "data modelling",
        ],
    },
    {
        "ofo_code": "25120101",
        "preferred_label": "Software Developer",
        "description": "Develops, tests, and maintains software applications and systems.",
        "parent_code": "25000000",
        "skills": [
            "python", "java", "javascript", "sql", "git", "agile development",
            "api development", "software testing", "debugging",
            "object-oriented programming", "web development",
        ],
    },
    {
        "ofo_code": "25120201",
        "preferred_label": "Web Developer",
        "description": "Designs and develops websites and web applications.",
        "parent_code": "25000000",
        "skills": [
            "html", "css", "javascript", "react", "node.js",
            "web development", "responsive design", "api integration",
            "version control", "frontend development", "backend development",
        ],
    },
    {
        "ofo_code": "25130101",
        "preferred_label": "Database Administrator",
        "description": "Manages and maintains database systems for performance and security.",
        "parent_code": "25000000",
        "skills": [
            "sql", "database administration", "data modelling", "performance tuning",
            "backup and recovery", "database security", "mysql", "postgresql",
            "oracle", "mongodb", "data warehousing",
        ],
    },
    {
        "ofo_code": "25130201",
        "preferred_label": "Data Analyst",
        "description": "Analyses data to support business decision-making and reporting.",
        "parent_code": "25000000",
        "skills": [
            "data analysis", "sql", "python", "statistical analysis",
            "data visualisation", "power bi", "tableau", "excel",
            "business intelligence", "reporting", "data cleaning",
        ],
    },
    {
        "ofo_code": "25130301",
        "preferred_label": "Data Scientist",
        "description": "Applies advanced analytics and machine learning to extract insights from data.",
        "parent_code": "25000000",
        "skills": [
            "machine learning", "python", "deep learning", "statistical modelling",
            "nlp", "tensorflow", "pytorch", "data mining",
            "predictive modelling", "ai ethics", "mlops", "sql",
        ],
    },
    {
        "ofo_code": "25210101",
        "preferred_label": "Network Administrator",
        "description": "Manages and maintains computer networks and telecommunications systems.",
        "parent_code": "25000000",
        "skills": [
            "network administration", "tcp/ip", "cisco", "routing", "switching",
            "firewall management", "network security", "vpn", "dns", "dhcp",
            "cloud networking", "network monitoring",
        ],
    },
    {
        "ofo_code": "25220101",
        "preferred_label": "Systems Administrator",
        "description": "Manages and maintains IT infrastructure and server systems.",
        "parent_code": "25000000",
        "skills": [
            "linux administration", "windows server", "cloud computing",
            "aws", "azure", "gcp", "docker", "kubernetes",
            "devops", "ci/cd", "infrastructure as code", "terraform",
        ],
    },
    {
        "ofo_code": "25230101",
        "preferred_label": "ICT Security Specialist",
        "description": "Protects organisational information systems from security threats.",
        "parent_code": "25000000",
        "skills": [
            "cybersecurity", "network security", "penetration testing",
            "vulnerability assessment", "security auditing", "risk management",
            "incident response", "firewall", "encryption", "siem",
        ],
    },
    {
        "ofo_code": "25140101",
        "preferred_label": "Mobile Application Developer",
        "description": "Develops applications for mobile devices and platforms.",
        "parent_code": "25000000",
        "skills": [
            "mobile development", "android", "ios", "kotlin", "swift",
            "react native", "flutter", "api integration",
            "mobile ui design", "app testing", "app store deployment",
        ],
    },
    {
        "ofo_code": "25140201",
        "preferred_label": "Cloud Architect",
        "description": "Designs and manages cloud computing strategies and infrastructure.",
        "parent_code": "25000000",
        "skills": [
            "cloud computing", "aws", "azure", "gcp",
            "cloud architecture", "microservices", "docker", "kubernetes",
            "devops", "infrastructure as code", "terraform", "cloud security",
        ],
    },
    {
        "ofo_code": "25290101",
        "preferred_label": "AI/ML Engineer",
        "description": "Designs and implements artificial intelligence and machine learning systems.",
        "parent_code": "25000000",
        "skills": [
            "artificial intelligence", "machine learning", "deep learning",
            "python", "tensorflow", "pytorch", "nlp", "computer vision",
            "mlops", "model deployment", "ai ethics", "data engineering",
        ],
    },
    {
        "ofo_code": "25290201",
        "preferred_label": "DevOps Engineer",
        "description": "Bridges development and operations through automation and CI/CD practices.",
        "parent_code": "25000000",
        "skills": [
            "devops", "ci/cd", "docker", "kubernetes", "jenkins",
            "git", "automation", "infrastructure as code", "terraform",
            "ansible", "monitoring", "cloud services",
        ],
    },
    {
        "ofo_code": "25150101",
        "preferred_label": "Quality Assurance Engineer",
        "description": "Designs and executes tests to ensure software quality and reliability.",
        "parent_code": "25000000",
        "skills": [
            "software testing", "test automation", "selenium", "pytest",
            "quality assurance", "test planning", "bug tracking",
            "api testing", "performance testing", "ci/cd integration",
        ],
    },
    {
        "ofo_code": "25160101",
        "preferred_label": "IT Project Manager",
        "description": "Manages IT projects including planning, execution, and stakeholder coordination.",
        "parent_code": "25000000",
        "skills": [
            "project management", "agile", "scrum", "stakeholder management",
            "risk management", "budgeting", "resource planning",
            "jira", "project documentation", "team leadership",
        ],
    },
    {
        "ofo_code": "13320101",
        "preferred_label": "ICT Manager",
        "description": "Directs and manages ICT strategy, operations, and service delivery.",
        "parent_code": "10000000",
        "skills": [
            "ict management", "it strategy", "service delivery management",
            "it governance", "team management", "vendor management",
            "itil", "budget management", "digital transformation",
        ],
    },
]

# OFO skills to be linked to occupations
OFO_SKILLS: List[Dict] = [
    {"ofo_code": "SKL001", "preferred_label": "Systems Analysis", "skill_type": "skill/competence"},
    {"ofo_code": "SKL002", "preferred_label": "Software Development", "skill_type": "skill/competence"},
    {"ofo_code": "SKL003", "preferred_label": "Web Development", "skill_type": "skill/competence"},
    {"ofo_code": "SKL004", "preferred_label": "Database Administration", "skill_type": "skill/competence"},
    {"ofo_code": "SKL005", "preferred_label": "Data Analysis", "skill_type": "skill/competence"},
    {"ofo_code": "SKL006", "preferred_label": "Data Science", "skill_type": "skill/competence"},
    {"ofo_code": "SKL007", "preferred_label": "Network Administration", "skill_type": "skill/competence"},
    {"ofo_code": "SKL008", "preferred_label": "Systems Administration", "skill_type": "skill/competence"},
    {"ofo_code": "SKL009", "preferred_label": "ICT Security", "skill_type": "skill/competence"},
    {"ofo_code": "SKL010", "preferred_label": "Cloud Computing", "skill_type": "skill/competence"},
    {"ofo_code": "SKL011", "preferred_label": "Mobile Development", "skill_type": "skill/competence"},
    {"ofo_code": "SKL012", "preferred_label": "Artificial Intelligence", "skill_type": "skill/competence"},
    {"ofo_code": "SKL013", "preferred_label": "DevOps", "skill_type": "skill/competence"},
    {"ofo_code": "SKL014", "preferred_label": "Quality Assurance", "skill_type": "skill/competence"},
    {"ofo_code": "SKL015", "preferred_label": "IT Project Management", "skill_type": "skill/competence"},
]


def get_seed_groups() -> List[Dict]:
    return OFO_MAJOR_GROUPS + OFO_SUB_GROUPS


def get_seed_occupations() -> List[Dict]:
    return OFO_OCCUPATIONS


def get_seed_skills() -> List[Dict]:
    return OFO_SKILLS
