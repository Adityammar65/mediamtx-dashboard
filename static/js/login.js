const form = document.getElementById('login-form');
const errorMessage = document.getElementById('login-error');
const submitButton = document.getElementById('login-submit');

form.addEventListener('submit', async event => {
    event.preventDefault();
    errorMessage.textContent = '';
    errorMessage.classList.add('hidden');
    submitButton.disabled = true;

    const formData = new FormData(form);
    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: formData.get('username'),
                password: formData.get('password'),
            }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || result.message || 'Unable to sign in. Check your credentials.');
        }

        window.location.replace('/');
    } catch (error) {
        errorMessage.textContent = error.message || 'Unable to sign in. Please try again.';
        errorMessage.classList.remove('hidden');
        submitButton.disabled = false;
    }
});
