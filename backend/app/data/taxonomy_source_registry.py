"""
Taxonomy source registry.

Records the expected provenance and checksums for the ESCO v1.2.0 English CSV
distribution. Local download/staging paths are deliberately excluded because
they are acquisition details, not part of the portable system provenance.
"""

ACA_INSPECTION = {
    "source": "European Commission ESCO v1.2.0 English CSV distribution",
    "version": "1.2.0",
    "licence": "EUPL v1.2 (ESCO data published under the European Union Public Licence v1.2)",
    "licence_url": "https://data.europa.eu/euodp/en/reuse/psd",
    "recorded_at": "2026-09-11T18:06:58Z",
    "corrected_at": "2026-09-12T00:00:00Z",
    "inspection": (
        "Official ESCO v1.2.0 English CSV distribution; validated by expected "
        "filenames, schema, row counts and SHA-256 checksums before import"
    ),
    "subset_note": (
        "The acquired files are an official-format PARTIAL SUBSET of the ESCO v1.2.0 English "
        "distribution (skills_en.csv 13,960 rows, occupations_en.csv 3,043 rows), not the full published "
        "distribution (104,064 skills / 35,203 occupations). Byte sizes and SHA-256 hashes are those of the "
        "acquired files; data_rows were re-counted directly from the acquired files (header excluded). "
        "The earlier coverage_summary figures reflected the published distribution totals and were corrected "
        "to the measured supplied-file counts on 2026-09-12."
    ),
    "coverage_summary": {
        "occupations": 3043,
        "skills": 13960,
        "isco_groups": 619,
        "occupation_skill_relations": 126051,
        "skill_skill_relations": 5818,
        "files": 19,
        "bytes_total": 51785655,
    },
    "files": [
        {"filename": "ISCOGroups_en.csv", "bytes": 966601, "data_rows": 619, "sha256": "7a829bb6fddccbdb028d3ae69d822f2f1ba581522667f6185949c6d0788eaa1c"},
        {"filename": "broaderRelationsOccPillar_en.csv", "bytes": 730008, "data_rows": 3648, "sha256": "b6b457a7b248e87734a5ef01f59f0bd4d083b6ad5e9251f6ed4cce51d69c6383"},
        {"filename": "broaderRelationsSkillPillar_en.csv", "bytes": 4944592, "data_rows": 20819, "sha256": "56b70f4852b1f53c6192c979310c34c93f95436621d907083cf0d55b51d8e42d"},
        {"filename": "conceptSchemes_en.csv", "bytes": 941042, "data_rows": 20, "sha256": "4e5b4800e6cdc2013df0f22dfff72c0499cdce8bf9cfa333d6c4c14879dce517"},
        {"filename": "dictionary_en.csv", "bytes": 19719, "data_rows": 160, "sha256": "f20857239063a52af0a7668ae5b178144cb33ff626519fb50451457d59b54fec"},
        {"filename": "digCompSkillsCollection_en.csv", "bytes": 18759, "data_rows": 25, "sha256": "814108ed9bc93268abc6d717bbd36f876a73180da2ff1a89b4f867c50e1ae9d4"},
        {"filename": "digitalSkillsCollection_en.csv", "bytes": 811101, "data_rows": 1284, "sha256": "9f2ee9179f0720826cbfc65627bd3642926ba4dfb3bf29250f22cb232c225b1e"},
        {"filename": "greenShareOcc_en.csv", "bytes": 452849, "data_rows": 3590, "sha256": "b181bde83460dbd766268893dd6db4393006c15d788ae4c0f3f41c49719ab16a"},
        {"filename": "greenSkillsCollection_en.csv", "bytes": 455125, "data_rows": 629, "sha256": "502eaee4f496e7576ee078a76d5da03fa14f5476f740ca965ca2ef596d9683ab"},
        {"filename": "languageSkillsCollection_en.csv", "bytes": 144359, "data_rows": 359, "sha256": "93b2ca9ef1300a34c2262753e33dbcf6a3a17ad7d2afe435849649818ec6cf33"},
        {"filename": "occupationSkillRelations_en.csv", "bytes": 27986628, "data_rows": 126051, "sha256": "e1a46511f0ef4d505f106f1d41f528ef76d289f93e59d4d0cbaac38986102c44"},
        {"filename": "occupations_en.csv", "bytes": 3047703, "data_rows": 3043, "sha256": "8034348d84b6d1dd24a5bcf9609186ecbba0a85457ee2eacd65bddec33a51b4a"},
        {"filename": "researchOccupationsCollection_en.csv", "bytes": 126900, "data_rows": 122, "sha256": "85993f6460b6bb008985cd40341c3d373fac9989d854f76d2d3c6fc8dc2d6d1a"},
        {"filename": "researchSkillsCollection_en.csv", "bytes": 27033, "data_rows": 40, "sha256": "fd9b6bd45df2bad68e50d963ac366b5c7dec2917e178e69003b6d94bb1e41d13"},
        {"filename": "skillGroups_en.csv", "bytes": 340935, "data_rows": 640, "sha256": "644b68a174299eb05336eec36e0716c4671a0c6bdd4ac268803ecd6533dc739d"},
        {"filename": "skillSkillRelations_en.csv", "bytes": 1031275, "data_rows": 5818, "sha256": "64a5f8fb7b8dda4932ff06db4738ce1beed3906e45a49b14453349056c609439"},
        {"filename": "skillsHierarchy_en.csv", "bytes": 381733, "data_rows": 640, "sha256": "295133872c6be7b7560de943efa4a6aab833a1b15af4d60c03b050ab0a75edcb"},
        {"filename": "skills_en.csv", "bytes": 9302000, "data_rows": 13960, "sha256": "d03b10efca94b4bcfa260a992cfde89c375f0fa12095d6662a663cfd2f9f2950"},
        {"filename": "transversalSkillsCollection_en.csv", "bytes": 57293, "data_rows": 95, "sha256": "40bd1884f1c62b91ab86b6c87d7fab11b082c17b425975d0d178d1b5cb5e01ca"},
    ],
}

OFO_INSPECTION = {
    "status": "deferred",
    "reason": (
        "OFO provenance is managed separately through the controlled DHET OFO acquisition workflow. "
        "OFO linkage remains deferred in this fallback record until an official acquired source is "
        "validated and recorded; the live imported-source record supersedes this fallback."
    ),
    "source": None,
    "version": None,
    "licence": None,
    "recorded_at": "2026-09-11T18:06:58Z",
}

DHET_OFO_2021_PROFILE = {
    "source_key": "dhet_ofo_2021",
    "name": "DHET Organising Framework for Occupations (OFO) 2021",
    "authority": "DHET",
    "category": "taxonomy/reference",
    "version": "2021",
    "source_page_url": "https://www.dhet.gov.za/SitePages/SkillsDevelopmentNew.aspx",
    "preferred_update": "Official Updated OFO Version 2021 structured workbook/file",
    "status": "pending_validation",
    "licence_note": (
        "Official South African government publication. Redistribution is subject to the "
        "terms published by DHET; the acquired file is stored in the approved evidence/source-data "
        "area (data/evidence/dhet_ofo_2021) and is not committed to source control."
    ),
    "discovery_note": (
        "A third-party mirror may be used only to locate the official file; if used it is recorded "
        "as discovery provenance and never as the authoritative source."
    ),
    "allowlisted_domains": ["www.dhet.gov.za", "dhet.gov.za"],
    "expected_sha256": None,
    "recorded_at": "2026-09-11T18:06:58Z",
}

TAXONOMY_PROVENANCE = {
    "inspection": ACA_INSPECTION,
    "ofo": OFO_INSPECTION,
    "dhet_ofo_2021": DHET_OFO_2021_PROFILE,
}
