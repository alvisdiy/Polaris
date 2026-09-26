<template>
  <div className="benefits">
    <strong>Benefits Include:</strong><br/>
    {scholarship.benefit.tuition_fee && <li>✓ Tuition Fee Covered</li>}
    {scholarship.benefit.monthly_allowance && <li>✓ Monthly Allowance</li>}
    {scholarship.benefit.accommodation && <li>✓ Accommodation</li>}
    {scholarship.benefit.health_insurance && <li>✓ Health Insurance</li>}
    {scholarship.benefit.travel_ticket && <li>✓ Travel Ticket</li>}
    {scholarship.benefit.research_grant && <li>✓ Research Grant</li>}
  </div>