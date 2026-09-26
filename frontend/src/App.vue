import { ref, onMounted, watch } from 'vue';

const API_BASE = '/api/v1/scholarships';

const state = {
  profile: {
    target_country: '',
    degree: '',
    field_of_study: [] as string[],
    current_gpa: 0,
    ielts_score: null,
    toefl_score: null,
    research_experience: 'Not Required',
    work_experience: 'Not Required',
    publication: 'Not Required',
    leadership: false,
    funding_preference: 'Fully Funded',
  },
  recommendations: [] as any[],
  loading: false,
  error: '',
  searchQuery: '',
  activeTab: 'recommendations' as 'recommendations' | 'details',
  selectedScholarship: null as any,
};

const fetchProfile = async () => {
  state.loading = true;
  state.error = '';
  try {
    const response = await fetch(`${API_BASE}/recommendations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(state.profile),
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Failed to fetch recommendations');
    }
    
    const data = await response.json();
    state.recommendations = data.results;
  } catch (error) {
    state.error = error.message;
  } finally {
    state.loading = false;
  }
};

const submitProfile = async () => {
  state.loading = true;
  state.error = '';
  try {
    const response = await fetch(`${API_BASE}/recommendations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(state.profile),
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'API error');
    }
    
    const data = await response.json();
    state.recommendations = data.results;
    state.error = '';
  } catch (error) {
    state.error = error.message;
  } finally {
    state.loading = false;
  }
}

const showDetail = (scholarship) => {
  state.selectedScholarship = sch;
  state.activeTab = 'details';
};

const goToProfile = () => {
  state.activeTab = 'recommendations';
  state.selectedScholarship = null;
  // Reset profile form if needed
  // For now, we'll assume profile is already filled
  fetchProfile();
}

const handleProfileChange = (e) => {
  const { name, value } = e.target;
  if (name === 'target_country') {
    state.profile.target_country = value;
  } else if (name === 'degree') {
    state.profile.degree = value;
  } else if (name === 'current_gpa') {
    state.profile.current_gpa = parseFloat(value) || 0;
  } else if (name === 'ielts_score') {
    state.profile.ielts_score = parseFloat(value) || null;
  } else if (name === 'toefl_score') {
    state.profile.toefl_score = parseInt(value) || null;
  } else if (name === 'research_experience') {
    state.profile.research_experience = value;
  } else if (name === 'work_experience') {
    state.profile.work_experience = value;
  } else if (name === 'publication') {
    state.profile.publication = value;
  } else if (name === 'leadership') {
    state.profile.leadership = value === 'true';
  } else if (name === 'funding_preference') {
    state.profile.funding_preference = value;
  }
};

const App = () => {
  onMounted(() => {
    fetchProfile();
  });

  return (
    <div className="container">
      <header>
        <h1>Polaris — Scholarship Discovery</h1>
        <p className="subtitle">Find, compare, and apply to scholarships</p>
        
        <nav>
          <button className="btn-sm" onClick={goToProfile} aria-label="View recommendations">
            View Recommendations
          </button>
        </nav>
      </header>
      
      <div className="grid-layout">
        {/* Left panel: Profile form */}
        <div className="card">
          <div className="card-title">Create Profile</div>
          <form>
            <div className="form-group">
              <label htmlFor="country">Country</label>
              <input 
                id="country" 
                name="target_country" 
                type="text" 
                value={state.profile.target_country} 
                onChange={handleProfileChange}
                placeholder="e.g., Japan"
                required
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="degree">Degree</label>
              <input 
                id="degree" 
                name="degree" 
                type="text" 
                value={state.profile.degree} 
                onChange={handleProfileChange}
                placeholder="e.g., Master"
                required
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="gpa">GPA</label>
              <input 
                id="gpa" 
                name="current_gpa" 
                type="number" 
                min="0" 
                max="4" 
                step="0.1" 
                value={state.profile.current_gpa} 
                onChange={handleProfileChange}
                placeholder="e.g., 3.5"
                required
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="ielts">IELTS Score</label>
              <input 
                id="ielts" 
                name="ielts_score" 
                type="number" 
                min="0" 
                max="9" 
                step="0.5" 
                value={state.profile.ielts_score === null ? '' : state.profile.ielts_score}
                onChange={handleProfileChange}
                placeholder="e.g., 7.0"
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="field">Field of Study</label>
              <input 
                id="field" 
                name="field_of_study" 
                type="text" 
                value={state.profile.field_of_study.join(', ')} 
                onChange={handleProfileChange}
                placeholder="e.g., Computer Science, Engineering"
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="leadership">Leadership Experience</label>
              <select 
                id="leadership" 
                name="leadership" 
                value={state.profile.leadership ? 'true' : 'false'}
                onChange={handleProfileChange}
                aria-label="Leadership experience"
              >
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </div>
            
            <div className="form-group">
              <label htmlFor="funding">Funding Preference</label>
              <select 
                id="funding" 
                name="funding_preference" 
                value={state.profile.funding_preference} 
                onChange={handleProfileChange}
                aria-label="Funding preference"
              >
                <option value="Fully Funded">Fully Funded</option>
                <option value="Partial Funded">Partial Funded</option>
                <option value="Tuition Only">Tuition Only</option>
              </select>
            </div>
            
            <div className="form-group">
              <button 
                type="button" 
                className="primary" 
                onClick={submitProfile}
              >
                Get Recommendations
              </button>
            </div>
          </form>
        </div>
        
        {/* Main content */}
        <div className="card">
          <div className="card-title">
            {state.activeTab === 'recommendations' ? 'Scholarship Recommendations' : 'Scholarship Detail'}
          </div>
          
          {state.activeTab === 'recommendations' && (
            <>
              {state.error && (
                <div className="card">
                  <div className="card-title">Error</div>
                  <div className="list-block">
                    <ul>
                      {state.error.split('.').map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              
              {state.loading && <div className="card">Loading recommendations...</div>}
              
              {state.error && (
                <div className="card">
                  <div className="card-title">Error</div>
                  <div className="list-block">
                    <ul>
                      {state.error.split('.').map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              
              {!state.loading && state.error === '' && (
                <div className="card">
                  <div className="card-title">Recommended Scholarships</div>
                  <div className="results">
                    {state.recommendations.length === 0 ? (
                      <div className="card">
                        <p>No scholarships match your criteria. Try adjusting your profile.</p>
                      </div>
                    ) : (
                      <div className="results">
                        {state.recommendations.map((sch, index) => (
                          <div key={index} className="scholarship-item">
                            <div className="scholarship-header">
                              <a 
                                href={sch.official_url} 
                                className="scholarship-title"
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {sch.scholarship_name}
                              </a>
                              <span className={`badge badge-${sch.match_score >= 85 ? 'excellent' : 
                                sch.match_score >= 70 ? 'strong' : 
                                sch.match_score >= 60 ? 'good' : 'info'}`}>
                                {sch.recommendation_category}
                              </span>
                            </div>
                            
                            <div className="meta-row">
                              <span>Deadline: {sch.deadline ? sch.deadline.toLocaleDateString() : 'No deadline'}</span>
                              <span>Provider: {sch.provider_name}</span>
                              <span>Country: {sch.country}</span>
                            </div>
                            
                            <div className="strengths-gaps">
                              <div>
                                <strong>Strengths:</strong>
                                {sch.strengths.map((s, i) => (
                                  <p key={i}>{s}</p>
                                )}
                              </div>
                              
                              <div>
                                <strong>Gaps:</strong>
                                {sch.gaps.map((g, i) => (
                                  <p key={i}>{g}</p>
                                )}
                              </div>
                            </div>
                            
                            <div className="actions">
                              <a 
                                href={sch.official_url} 
                                className="btn-sm primary" 
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                Apply Now
                              </a>
                            </div>
                          </div>
                        ))}
                  </div>
                </div>
              )}
              
              {state.error && (
                <div className="card">
                  <div className="card-title">Error</div>
                  <div className="list-block">
                    <ul>
                      {state.error.split('.').map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </>
          )}
          
          {state.activeTab === 'details' && state.selectedScholarship && (
            <div className="card">
              <div className="card-title">Scholarship Detail</div>
              <div className="meta-row">
                <span>Name: {state.selectedScholarship.scholarship_name}</span>
                <span>Provider: {state.selectedScholarship.provider_name}</span>
                <span>Country: {state.selectedScholarship.country}</span>
                <span>Degree: {state.selectedScholarship.degree}</span>
                <span>Funding: {state.selectedScholarship.funding_type}</span>
              </div>
              
              <div className="card">
                <h3>Requirements</div>
                {state.selectedScholarship.requirement 
                  ? <ScholarshipRequirementSchema 
                                    scholarship={state.selectedScholarship} 
                                    showDetails={true} /> 
                    : <p>No specific requirements listed</div>
                  >
                {state.selectedScholarship.benefit 
                  ? <ScholarshipBenefitSchema 
                                    scholarship={state.selectedScholarship} 
                                    showDetails={true} /> 
                  : <div>No benefits listed</div>
                  >
                {state.selectedScholarship.timeline 
                  ? <ScholarshipTimelineSchema 
                                    scholarship={state.selectedScholarship} 
                                    showDetails={true} /> 
                  : <div>Timeline information not available</div>
                  >
                <div className="actions">
                  <a 
                    href={state.selectedScholarship.official_url} 
                    className="btn-sm primary" 
                    target="_blank" 
                    rel="noopener noreferrer"
                  >
                    Official Application
                  </a>
                </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

function App() {
  return (
    <div className="container">
      <header>
        <h1>Polaris — Scholarship Discovery</h1>
        <p className="subtitle">Find, compare, and apply to scholarships</p>
        
        <nav>
          <button className="btn-sm" onClick={goToProfile} aria-label="View recommendations">
            View Recommendations
          </button>
        </nav>
      </header>
      
      <div className="grid-layout">
        {/* Left panel: Profile form */}
        <div className="card">
          <div className="card-title">Create Profile</div>
          <form>
            <div className="form-group">
              <label htmlFor="country">Country</label>
              <input 
                id="country" 
                name="target_country" 
                type="text" 
                value={state.profile.target_country} 
                onChange={handleProfileChange}
                placeholder="e.g., Japan"
                required
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="degree">Degree</label>
              <input 
                id="degree" 
                name="degree" 
                type="text" 
                value={state.profile.degree} 
                onChange={handleProfileChange}
                placeholder="e.g., Master"
                required
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="gpa">GPA</label>
              <input 
                id="gpa" 
                name="current_gpa" 
                type="number" 
                min="0" 
                max="4" 
                step="0.1" 
                value={state.profile.current_gpa} 
                onChange={handleProfileChange}
                placeholder="e.g., 3.5"
                required
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="ielts">IELTS Score</label>
              <input 
                id="ielts" 
                name="ielts_score" 
                type="number" 
                min="0" 
                max="9" 
                step="0.5" 
                value={state.profile.ielts_score === null ? '' : state.profile.ielts_score}
                onChange={handleProfileChange}
                placeholder="e.g., 7.0"
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="field">Field of Study</label>
              <input 
                id="field" 
                name="field_of_study" 
                type="text" 
                value={state.profile.field_of_study.join(', ')} 
                onChange={handleProfileChange}
                placeholder="e.g., Computer Science, Engineering"
              />
            </div>
            
            <div className="form-group">
              <label htmlFor="leadership">Leadership Experience</label>
              <select 
                id="leadership" 
                name="leadership" 
                value={state.profile.leadership ? 'true' : 'false'}
                onChange={handleProfileChange}
                aria-label="Leadership experience"
              >
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </div>
            
            <div className="form-group">
              <label htmlFor="funding">Funding Preference</label>
              <select 
                id="funding" 
                name="funding_preference" 
                value={state.profile.funding_preference} 
                onChange={handleProfileChange}
                aria-label="Funding preference"
              >
                <option value="Fully Funded">Fully Funded</option>
                <option value="Partial Funded">Partial Funded</option>
                <option value="Tuition Only">Tuition Only</option>
              </select>
            </div>
            
            <div className="form-group">
              <button 
                type="button" 
                className="primary" 
                onClick={submitProfile}
              >
                Get Recommendations
              </button>
            </div>
          </form>
        </div>
        
        {/* Main content */}
        <div className="card">
          <div className="card-title">
            {state.activeTab === 'recommendations' ? 'Scholarship Recommendations' : 'Scholarship Detail'}
          </div>
          
          {state.activeTab === 'recommendations' && (
            <>
              {state.error && (
                <div className="card">
                  <div className="card-title">Error</div>
                  <div className="list-block">
                    <ul>
                      {state.error.split('.').map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              
              {state.loading && (
                <div className="card">
                  <p>Loading recommendations...</div>
                </div>
              )}
              
              {state.recommendations.length > 0 && (
                <div className="results">
                  {state.recommendations.map((sch, index) => (
                    <div className="scholarship-item" key={index}>
                      <div className="scholarship-header">
                        <a 
                          href={sch.official_url} 
                          className="scholarship-title"
                          target="_blank" 
                          rel="noopener noreferrer"
                        >
                          {sch.scholarship_name}
                        </a>
                        <span className={`badge badge-${sch.match_score >= 85 ? 'excellent' : 
                          sch.match_score >= 70 ? 'strong' : 
                          sch.match_score >= 60 ? 'good' : 'info'}`}>
                          {sch.recommendation_category}
                        </span>
                      </div>
                      
                      <div className="meta-row">
                        <span>Deadline: {sch.deadline ? sch.deadline.toLocaleDateString() : 'No deadline'}</span>
                        <span>Provider: {sch.provider_name}</span>
                        <span>Country: {sch.country}</span>
                      </div>
                      
                      <div className="strengths-gaps">
                        <div>
                          <strong>Strengths:</strong>
                          {sch.strengths.map((s, i) => (
                            <p key={i}>{s}</p>
                          ))}
                        </div>
                        
                        <div>
                          <strong>Gaps:</strong>
                          {sch.gaps.map((g, i) => (
                            <p key={i}>{g}</p>
                          ))}
                        </div>
                      </div>
                      
                      <div className="actions">
                        <a 
                          href={sch.official_url} 
                          className="btn-sm primary" 
                          target="_blank" 
                          rel="noopener noreferrer"
                        >
                          Apply Now
                        </a>
                      </div>
                    </div>
                  )}
                </div>
              )}
              
              {state.activeTab === 'details' && state.selectedScholarship && (
                <div className="card">
                  <div className="card-title">Scholarship Detail</div>
                  <div className="meta-row">
                    <span>Name: {state.selectedScholarship.scholarship_name}</span>
                    <span>Provider: {state.selectedScholarship.provider_name}</span>
                    <span>Country: {state.selectedScholarship.country}</span>
                    <span>Degree: {state.selectedScholarship.degree}</span>
                    <span>Funding: {state.selectedScholarship.funding_type}</span>
                  </div>
                  
                  <div className="requirements">
                    <ScholarshipRequirementDetail 
                      scholarship={state.selectedScholarship} 
                    />
                  </div>
                  
                  <div className="benefits">
                    <ScholarshipBenefitDetail 
                      scholarship={state.selectedScholarship} 
                    />
                  </div>
                  
                  <div className="timeline">
                    <ScholarshipTimelineDetail 
                      scholarship={state.selectedScholarship} 
                    />
                  </div>
                  
                  <div className="actions">
                    <a 
                      href={state.selectedScholarship.official_url} 
                      className="btn-sm primary" 
                      target="_blank" 
                      rel="noopener noreferrer"
                    >
                      Official Application
                    </a>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default App;