// Event listener to track HTMX swap events
document.addEventListener('htmx:afterSwap', function (event) {
    // Check to see if the edit modal has been populated
    var manualRadio = document.getElementById('manualRadio');
    var automaticRadio = document.getElementById('automaticRadio');
    var keywordSection = document.getElementById('keywordSection');

    if (manualRadio && automaticRadio && keywordSection) {
        manualRadio.addEventListener('change', function () {
            keywordSection.classList.toggle('hidden', !this.checked);
            document.querySelector('input[name="keywords"]').required = true;
        });

        automaticRadio.addEventListener('change', function () {
            keywordSection.classList.add('hidden');
            document.querySelector('input[name="keywords"]').required = false;
        });
    }

    if (event.detail.target.id === 'modalContent') {
        // Show the modal when new content is loaded into modalContent
        document.getElementById('modal').classList.toggle('hidden');
    }
});

// Modal specific Event listener to close the modal dialog
document.addEventListener('click', function (event) {
    if (event.target.id === 'closeBtn') {
        // Toggle the modal visibility
        document.getElementById('modal').classList.toggle('hidden');
    }
});


// Event listener to capture last focussed element to track the Flow being edited
let lastFocusedRow = null;

document.addEventListener('focusin', function (e) {
    if (e.target.closest('tr')) {  // Check if the focused element is inside a table row
        lastFocusedRow = e.target.closest('tr');
    }
});

document.addEventListener('htmx:beforeRequest', function (event) {
    // Initialize headers object if it doesn't exist
    if (!event.detail.headers) {
        event.detail.headers = {};
    }

    if (lastFocusedRow) {
        // Add custom header with information about the focused element
        event.detail.headers['Focused-Row'] = lastFocusedRow.id;
    }
});
