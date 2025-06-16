import './scss/app.scss';

import 'popper.js';  // Needed for bootstrap tooltips.

import 'bootstrap';

// Expose bootstrap, so that we can initiate some events with it (like enabling tooltips).
window.bootstrap = require('bootstrap/dist/js/bootstrap.bundle.js');
