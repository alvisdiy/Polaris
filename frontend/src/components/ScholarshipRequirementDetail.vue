<template>
  <div className="requirements">
    <strong>Minimum GPA:</strong> {req.minimum_gpa || 'Not specified'}<br/>
    <strong>IELTS Required:</strong> {req.ielts_required ? 'Yes' : 'No'}<br/>
    {req.minimum_ielts && <br/> <strong>Minimum IELTS:</strong> {req.minimum_ielts}}<br/>
    <strong>TOEFL Required:</strong> {req.toefl_required ? 'Yes' : 'No'}<br/>
    {req.minimum_toefl && <br/> <strong>Minimum TOEFL:</strong> {req.minimum_toefl}}<br/>
    <strong>Work Experience:</strong> {req.work_experience || 'Not specified'}<br/>
    <strong>Research Experience:</strong> {req.research_experience || 'Not specified'}<br/>
    <strong>Publication:</strong> {req.publication || 'Not required'}
  </div>