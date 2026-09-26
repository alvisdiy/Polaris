<template>
  <div className="timeline">
    <strong>Timeline:</strong><br/>
    {scholarship.timeline.application_open && <div>Application Open: {scholarship.timeline.application_open}</div>}
    {scholarship.timeline.application_deadline && <div>Application Deadline: {scholarship.timeline.application_deadline}</div>}
    {scholarship.timeline.application_cycle && <div>Application Cycle: {scholarship.timeline.application_cycle}</div>}
  </div>