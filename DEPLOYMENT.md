# Relay walkthrough deployment

Vercel team: JR (`team_DxIWznyiQHtapw46Zc0gALfw`).
Project: `relay-recovery-preview` (`prj_cQvJReJKHpGAc6ETtQFl2rmYDjbG`).
Verified Preview build: `dpl_Gnpc6yF5awbcNkhpfKzAtADqv9ik`.
Deployment: https://relay-recovery-preview-5h65c1hvb-jr-3f25.vercel.app/
Vercel API environment name: `staging` (Preview).

Vercel made the first build of this new isolated demo project its default deployment
(`dpl_26RvL8L9NR9XoPgNJCxFny7TxFak`). It contains the same sample-only source.
The reviewed share link points to the explicit Preview build above. No existing
project, custom domain, CRM, email account or production customer data was changed.

Deployment Protection remains enabled. A deployment-scoped share link is available
for forwarding; its token is intentionally not stored in this repository. The link
issued on 27 October expires 3 November 2026 at 22:32 GMT. Use Vercel's share-link
tools to renew it when needed; do not disable project protection to test the app.

Verification: 43 automated tests; JavaScript syntax checks; desktop/phone browser
inspection; deployed sample filtering, template generation, approval, booking,
cancellation of the old recovery job, persistence across reload, reset, and a
successful live health response. Browser warnings/errors were empty. A complete
sample journey through attendance, settlement and refunds was also exercised in
automated tests; attendance and settlement were verified in the local browser.

Only allowlisted Python modules, static assets, requirements and the Python version
were uploaded through Vercel's source-file API. Databases and environment files were
excluded. The repository versions the preview source, its verification tests and
desktop/mobile screenshots alongside the persistent product. GitHub updates do
not automatically redeploy this source-file-based Vercel project.
