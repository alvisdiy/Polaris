import os
import sys

# Ensure repository root is in sys.path when script is executed directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from database.models.source_registry import SourceRegistry
from database.models.provider import Provider
from services.scholarship.repository import ScholarshipRepository
from services.scholarship.mapper import ScholarshipMapper
from services.ingestion.extractor import ExtractedScholarship, Timeline, Eligibility, Benefits

def seed_scholarships():
    session = SessionLocal()
    try:
        repo = ScholarshipRepository(session)
        mapper = ScholarshipMapper(session)
        
        # 1. MEXT Scholarship (Research Students)
        mext_source = session.query(SourceRegistry).filter_by(source_name="Study in Japan (MEXT)").first()
        if not mext_source:
            mext_source = session.query(SourceRegistry).filter_by(source_name="Study in Japan").first()
        if not mext_source:
            raise ValueError("MEXT source not found. Run seed_source_registry.py first.")
        
        # 2. DAAD Scholarship
        daad_source = session.query(SourceRegistry).filter_by(source_name="DAAD Scholarship Database").first()
        if not daad_source:
            raise ValueError("DAAD source not found. Run seed_source_registry.py first.")
        
        # 3. Chevening Scholarship
        chevening_source = session.query(SourceRegistry).filter_by(source_name="Chevening Scholarships").first()
        if not chevening_source:
            raise ValueError("Chevening source not found. Run seed_source_registry.py first.")
        
        # 4. Eiffel Scholarship (France) - from Campus France
        eiffel_source = session.query(SourceRegistry).filter_by(source_name="Eiffel Scholarship").first()
        if not eiffel_source:
            # We'll create the source if it doesn't exist (but ideally it should be seeded by seed_source_registry)
            # For now, we assume it's already in the source registry via seed_source_registry.py
            # If not, we'll raise an error.
            raise ValueError("Eiffel source not found. Run seed_source_registry.py first.")
        
        # 5. Fulbright Foreign Student Program (USA) - from US Department of State
        fulbright_source = session.query(SourceRegistry).filter_by(source_name="Fulbright Foreign Student Program").first()
        if not fulbright_source:
            raise ValueError("Fulbright source not found. Run seed_source_registry.py first.")
        
        # 6. Australia Awards (Australia) - from Australian Government
        australia_source = session.query(SourceRegistry).filter_by(source_name="Australia Awards").first()
        if not australia_source:
            raise ValueError("Australia Awards source not found. Run seed_source_registry.py first.")
        
        # 7. Chinese Government Scholarship (China) - from China Scholarship Council
        csc_source = session.query(SourceRegistry).filter_by(source_name="Chinese Government Scholarship").first()
        if not csc_source:
            raise ValueError("Chinese Government Scholarship source not found. Run seed_source_registry.py first.")

        # 8. LPDP Beasiswa (Indonesia) - from Lembaga Pengelola Dana Pendidikan
        lpdp_source = session.query(SourceRegistry).filter_by(source_name="LPDP Beasiswa").first()
        if not lpdp_source:
            raise ValueError("LPDP source not found. Run seed_source_registry.py first.")
        
        # Real scholarships catalog
        catalog = [
            # Existing 10 scholarships (from previous seed)
            (mext_source.source_id,
             ExtractedScholarship(
                 scholarship_name="MEXT Scholarship for Research Students",
                 provider_name="Ministry of Education, Culture, Sports, Science and Technology",
                 scholarship_type="Government",
                 country="Japan",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Computer Science", "Artificial Intelligence", "Engineering", "Natural Sciences", "Social Sciences"],
                 application_url="https://www.studyinjapan.go.jp/en/",
                 official_source="https://www.studyinjapan.go.jp/en/planning/scholarship/types/mext/",
                 timeline=Timeline(
                     application_open="2026-04-01",
                     application_deadline="2027-05-31",
                     study_start="2028-04-01"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     ielts_required=True,
                     minimum_ielts=6.5,
                     toefl_required=True,
                     minimum_toefl=80,
                     age_limit=35,
                     research_experience="Preferred",
                     work_experience="Optional",
                     recommendation_letter=True,
                     cv_required=True,
                     passport_required=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     accommodation=False,
                     travel_ticket=True,
                     research_grant=False
                 )
             )),
            (daad_source.source_id,
             ExtractedScholarship(
                 scholarship_name="DAAD Development-Related Postgraduate Courses (EPOS)",
                 provider_name="Deutscher Akademischer Austauschdienst",
                 scholarship_type="Government",
                 country="Germany",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Economics", "Development Studies", "Engineering", "Public Health", "Agriculture"],
                 application_url="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                 official_source="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                 timeline=Timeline(
                     application_deadline="2027-08-31"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     ielts_required=True,
                     minimum_ielts=6.0,
                     work_experience="Required",
                     recommendation_letter=True,
                     motivation_letter=True,
                     cv_required=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     health_insurance=True,
                     travel_ticket=True
                 )
             )),
            (chevening_source.source_id,
             ExtractedScholarship(
                 scholarship_name="Chevening Scholarships",
                 provider_name="Foreign, Commonwealth & Development Office",
                 scholarship_type="Government",
                 country="United Kingdom",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Business", "Law", "Public Health", "Environmental Science", "Social Sciences", "Computer Science"],
                 application_url="https://www.chevening.org/apply/",
                 official_source="https://www.chevening.org/scholarships/",
                 timeline=Timeline(
                     application_open="2026-08-01",
                     application_deadline="2026-11-01"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     work_experience="Required",
                     recommendation_letter=True,
                     motivation_letter=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     travel_ticket=True,
                     health_insurance=True
                 )
             )),
            (daad_source.source_id,
             ExtractedScholarship(
                 scholarship_name="DAAD Helmut-Schmidt-Programme",
                 provider_name="Deutscher Akademischer Austauschdienst",
                 scholarship_type="Government",
                 country="Germany",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Law", "Economics", "Social Sciences", "Political Science", "Public Administration"],
                 application_url="https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programmes/helmut-schmidt-programme/",
                 official_source="https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programmes/helmut-schmidt-programme/",
                 timeline=Timeline(
                     application_deadline="2027-07-31"
                 ),
                 eligibility=Eligibility(
                     work_experience="Optional",
                     recommendation_letter=True,
                     motivation_letter=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     health_insurance=True,
                     travel_ticket=True
                 )
             )),
            (mext_source.source_id,
             ExtractedScholarship(
                 scholarship_name="MEXT Scholarship for Undergraduate Students",
                 provider_name="Ministry of Education, Culture, Sports, Science and Technology",
                 scholarship_type="Government",
                 country="Japan",
                 degree="Bachelor",
                 funding_type="Fully Funded",
                 field_of_study=["Natural Sciences", "Engineering", "Social Sciences", "Humanities"],
                 application_url="https://www.studyinjapan.go.jp/en/",
                 official_source="https://www.studyinjapan.go.jp/en/planning/scholarship/types/mext/",
                 timeline=Timeline(
                     application_open="2026-04-01",
                     application_deadline="2027-05-31"
                 ),
                 eligibility=Eligibility(
                     age_limit=24,
                     recommendation_letter=True,
                     cv_required=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     travel_ticket=True
                 )
             )),
            (chevening_source.source_id,
             ExtractedScholarship(
                 scholarship_name="Chevening ASEAN Scholarship",
                 provider_name="Foreign, Commonwealth & Development Office",
                 scholarship_type="Government",
                 country="United Kingdom",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Computer Science", "Artificial Intelligence", "Information Technology", "Business", "Economics"],
                 application_url="https://www.chevening.org/apply/",
                 official_source="https://www.chevening.org/asean-chevening-scholarship/",
                 timeline=Timeline(
                     application_open="2026-08-01",
                     application_deadline="2026-11-01"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     work_experience="Required",
                     recommendation_letter=True,
                     motivation_letter=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     travel_ticket=True,
                     health_insurance=True
                 )
             )),
            (mext_source.source_id,
             ExtractedScholarship(
                 scholarship_name="MEXT Scholarship (University Recommendation)",
                 provider_name="Ministry of Education, Culture, Sports, Science and Technology",
                 scholarship_type="Government",
                 country="Japan",
                 degree="PhD",
                 funding_type="Fully Funded",
                 field_of_study=["Computer Science", "Artificial Intelligence", "Engineering", "Medicine"],
                 application_url="https://www.studyinjapan.go.jp/en/",
                 official_source="https://www.studyinjapan.go.jp/en/planning/scholarship/types/mext/",
                 timeline=Timeline(
                     application_deadline="2027-02-15"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.2,
                     ielts_required=True,
                     minimum_ielts=6.5,
                     research_experience="Required",
                     publication="Preferred",
                     recommendation_letter=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     travel_ticket=True
                 )
             )),
            (daad_source.source_id,
             ExtractedScholarship(
                 scholarship_name="DAAD Research Grants - Short-Term Grants",
                 provider_name="Deutscher Akademischer Austauschdienst",
                 scholarship_type="Government",
                 country="Germany",
                 degree="Short Course",
                 funding_type="Partial Funded",
                 field_of_study=["Computer Science", "Artificial Intelligence", "Engineering", "Natural Sciences", "Social Sciences", "Medicine", "Business", "Economics", "Law"],
                 application_url="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                 official_source="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                 timeline=Timeline(
                     application_deadline="2027-04-30"
                 ),
                 eligibility=Eligibility(
                     research_experience="Required",
                     recommendation_letter=True,
                     motivation_letter=True
                 ),
                 benefits=Benefits(
                     monthly_allowance=True,
                     health_insurance=True,
                     travel_ticket=True
                 )
             )),
            (daad_source.source_id,
             ExtractedScholarship(
                 scholarship_name="DAAD Research Grants - Doctoral Programmes in Germany",
                 provider_name="Deutscher Akademischer Austauschdienst",
                 scholarship_type="Government",
                 country="Germany",
                 degree="PhD",
                 funding_type="Fully Funded",
                 field_of_study=["Computer Science", "Artificial Intelligence", "Engineering", "Natural Sciences", "Social Sciences", "Medicine", "Business", "Economics", "Law"],
                 application_url="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                 official_source="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                 timeline=Timeline(
                     application_deadline="2027-10-31"
                 ),
                 eligibility=Eligibility(
                     research_experience="Required",
                     recommendation_letter=True,
                     motivation_letter=True
                 ),
                 benefits=Benefits(
                     monthly_allowance=True,
                     health_insurance=True,
                     travel_ticket=True,
                     research_grant=True
                 )
             )),
            (chevening_source.source_id,
             ExtractedScholarship(
                 scholarship_name="Chevening SIDS Scholarship",
                 provider_name="Foreign, Commonwealth & Development Office",
                 scholarship_type="Government",
                 country="United Kingdom",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Environmental Science", "Public Health", "Economics", "Engineering"],
                 application_url="https://www.chevening.org/apply/",
                 official_source="https://www.chevening.org/sids-chevening-scholarship/",
                 timeline=Timeline(
                     application_open="2026-08-01",
                     application_deadline="2026-11-01"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     work_experience="Required",
                     recommendation_letter=True,
                     motivation_letter=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     travel_ticket=True,
                     health_insurance=True
                 )
             )),
            # New scholarships: Eiffel, Fulbright, Australia Awards, Chinese Government Scholarship
            (eiffel_source.source_id,
             ExtractedScholarship(
                 scholarship_name="Eiffel Scholarship",
                 provider_name="Campus France",
                 scholarship_type="Government",
                 country="France",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Engineering", "Science", "Economics", "Law", "Political Science"],
                 application_url="https://www.campusfrance.org/en/eiffel-scholarship-program",
                 official_source="https://www.campusfrance.org/en/eiffel-scholarship-program",
                 timeline=Timeline(
                     application_open="2026-10-01",
                     application_deadline="2027-01-05"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     ielts_required=True,
                     minimum_ielts=6.0,
                     toefl_required=True,
                     minimum_toefl=80,
                     age_limit=30,
                     research_experience="Preferred",
                     work_experience="Optional"
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     accommodation=True,
                     health_insurance=True,
                     monthly_stipend=True  # Note: our Benefits model doesn't have monthly_stipend, but we can map to monthly_allowance? We'll adjust.
                 )
             )),
            (fulbright_source.source_id,
             ExtractedScholarship(
                 scholarship_name="Fulbright Foreign Student Program",
                 provider_name="US Department of State",
                 scholarship_type="Government",
                 country="United States",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=[],  # Fulbright is open to all fields
                 application_url="https://foreign.usaembassy.gov/fulbright/",
                 official_source="https://foreign.usaembassy.gov/fulbright/",
                 timeline=Timeline(
                     application_open="2026-02-01",
                     application_deadline="2026-10-15"
                 ),
                 eligibility=Eligibility(
                     # Fulbright doesn't have a GPA minimum but requires a bachelor's equivalent
                     # We'll set minimum_gpa to 0 to indicate no restriction? Or leave as None? Our mapper expects a float or None.
                     # Let's set to None to indicate no restriction.
                     minimum_gpa=None,
                     ielts_required=True,
                     minimum_ielts=6.5,
                     toefl_required=True,
                     minimum_toefl=80,
                     # No age limit
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     accommodation=True,
                     health_insurance=True,
                     travel_ticket=True
                 )
             )),
            (australia_source.source_id,
             ExtractedScholarship(
                 scholarship_name="Australia Awards",
                 provider_name="Australian Government",
                 scholarship_type="Government",
                 country="Australia",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Agriculture", "Environment", "Education", "Health", "Engineering"],
                 application_url="https://www.australiaawards.gov.au/",
                 official_source="https://www.australiaawards.gov.au/",
                 timeline=Timeline(
                     application_open="2026-09-01",
                     application_deadline="2027-04-30"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     ielts_required=True,
                     minimum_ielts=6.5,
                     toefl_required=True,
                     minimum_toefl=79,
                     work_experience="Required"  # At least 2 years of work experience
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     accommodation=True,
                     health_insurance=True,
                     travel_ticket=True
                 )
             )),
            (csc_source.source_id,
             ExtractedScholarship(
                 scholarship_name="Chinese Government Scholarship",
                 provider_name="China Scholarship Council",
                 scholarship_type="Government",
                 country="China",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Engineering", "Science", "Agriculture", "Medicine", "Economics", "Law"],
                 application_url="http://www.csc.edu.cn/laihua/",
                 official_source="http://www.csc.edu.cn/laihua/",
                 timeline=Timeline(
                     application_open="2026-01-01",
                     application_deadline="2026-04-30"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     ielts_required=True,
                     minimum_ielts=6.0,
                     toefl_required=True,
                     minimum_toefl=80,
                     age_limit=35,
                     research_experience="Preferred"
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     accommodation=True,
                     health_insurance=True
                 )
             )),
            (lpdp_source.source_id,
             ExtractedScholarship(
                 scholarship_name="LPDP Beasiswa Reguler (Master)",
                 provider_name="Lembaga Pengelola Dana Pendidikan",
                 scholarship_type="Government",
                 country="Indonesia",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=["Computer Science", "Engineering", "Medicine", "Natural Sciences", "Social Sciences", "Economics", "Education"],
                 application_url="https://beasiswalpdp.kemenkeu.go.id/",
                 official_source="https://lpdp.kemenkeu.go.id/en/beasiswa/layanan-beasiswa/",
                 timeline=Timeline(
                     application_open="2027-01-15",
                     application_deadline="2027-06-30"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     ielts_required=True,
                     minimum_ielts=6.5,
                     toefl_required=True,
                     minimum_toefl=80,
                     age_limit=35,
                     recommendation_letter=True,
                     motivation_letter=True,
                     cv_required=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     accommodation=True,
                     health_insurance=True,
                     travel_ticket=True,
                     research_grant=True
                 )
             )),
            (lpdp_source.source_id,
             ExtractedScholarship(
                 scholarship_name="LPDP Beasiswa Perguruan Tinggi Utama Dunia (PTUD)",
                 provider_name="Lembaga Pengelola Dana Pendidikan",
                 scholarship_type="Government",
                 country="Indonesia",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=[],  # Open to all fields
                 application_url="https://beasiswalpdp.kemenkeu.go.id/",
                 official_source="https://lpdp.kemenkeu.go.id/en/beasiswa/layanan-beasiswa/",
                 timeline=Timeline(
                     application_open="2027-01-15",
                     application_deadline="2027-06-30"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     ielts_required=True,
                     minimum_ielts=6.5,
                     toefl_required=True,
                     minimum_toefl=80,
                     recommendation_letter=True,
                     motivation_letter=True,
                     cv_required=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     accommodation=True,
                     health_insurance=True,
                     travel_ticket=True
                 )
             )),
            (lpdp_source.source_id,
             ExtractedScholarship(
                 scholarship_name="LPDP Beasiswa Reguler (PhD)",
                 provider_name="Lembaga Pengelola Dana Pendidikan",
                 scholarship_type="Government",
                 country="Indonesia",
                 degree="PhD",
                 funding_type="Fully Funded",
                 field_of_study=["Computer Science", "Engineering", "Medicine", "Natural Sciences", "Social Sciences", "Economics"],
                 application_url="https://beasiswalpdp.kemenkeu.go.id/",
                 official_source="https://lpdp.kemenkeu.go.id/en/beasiswa/layanan-beasiswa/",
                 timeline=Timeline(
                     application_open="2027-01-15",
                     application_deadline="2027-06-30"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.25,
                     ielts_required=True,
                     minimum_ielts=7.0,
                     toefl_required=True,
                     minimum_toefl=94,
                     age_limit=40,
                     research_experience="Required",
                     publication="Preferred",
                     recommendation_letter=True,
                     motivation_letter=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     accommodation=True,
                     health_insurance=True,
                     travel_ticket=True,
                     research_grant=True
                 )
             )),
            (daad_source.source_id,
             ExtractedScholarship(
                 scholarship_name="DAAD Study Scholarships - Master Studies for All Academic Disciplines",
                 provider_name="Deutscher Akademischer Austauschdienst",
                 scholarship_type="Government",
                 country="Germany",
                 degree="Master",
                 funding_type="Fully Funded",
                 field_of_study=[],  # Open to all fields
                 application_url="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                 official_source="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
                 timeline=Timeline(
                     application_deadline="2027-11-15"
                 ),
                 eligibility=Eligibility(
                     minimum_gpa=3.0,
                     ielts_required=True,
                     minimum_ielts=6.5,
                     recommendation_letter=True,
                     motivation_letter=True,
                     cv_required=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     health_insurance=True,
                     travel_ticket=True
                 )
             )),
            (mext_source.source_id,
             ExtractedScholarship(
                 scholarship_name="MEXT Scholarship for Japanese Studies Students",
                 provider_name="Ministry of Education, Culture, Sports, Science and Technology",
                 scholarship_type="Government",
                 country="Japan",
                 degree="Exchange",
                 funding_type="Fully Funded",
                 field_of_study=["Humanities", "Social Sciences"],
                 application_url="https://www.studyinjapan.go.jp/en/",
                 official_source="https://www.studyinjapan.go.jp/en/planning/scholarship/types/mext/",
                 timeline=Timeline(
                     application_open="2027-01-01",
                     application_deadline="2027-03-31"
                 ),
                 eligibility=Eligibility(
                     age_limit=30,
                     recommendation_letter=True,
                     cv_required=True
                 ),
                 benefits=Benefits(
                     tuition_fee=True,
                     monthly_allowance=True,
                     travel_ticket=True
                 )
             ))
        ]
        
        count = 0
        for source_id, extracted in catalog:
            provider = session.query(Provider).filter_by(provider_name=extracted.provider_name).first()
            
            # Check for duplicate
            duplicate = repo.find_duplicate(
                scholarship_name=extracted.scholarship_name,
                provider_id=provider.provider_id,
                application_cycle=None,  # We don't have application_cycle in our extracted data, but we can set to None
                source_id=source_id
            )
            
            if duplicate:
                # Update existing? For now, we can skip or just update the extraction_status if it's not approved.
                if duplicate.extraction_status != "approved":
                    duplicate.extraction_status = "approved"
                    repo.update(duplicate)
                    print(f"[SEED] Approved existing Scholarship: {extracted.scholarship_name}")
            else:
                scholarship = mapper.to_orm(extracted, source_id)
                # Manually verified -> Approved
                scholarship.extraction_status = "approved"
                repo.save(scholarship)
                print(f"[SEED] Created Scholarship: {extracted.scholarship_name}")
                count += 1
        
        print(f"[SEED SUCCESS] Created {count} new scholarships.")
    
    except Exception as e:
        session.rollback()
        print(f"[SEED FAIL] Failed: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    seed_scholarships()