/**
 * Member add form: frontend validation before submission.
 */

const initMemberAddForm = () => {
  const form = document.querySelector('form[method="post"]');
  if (!form) return;

  const emailInput = document.querySelector('input[name="email"]');
  const roleSelect = document.querySelector('select[name="role"]');

  form.addEventListener('submit', (e) => {
    let isValid = true;
    let firstInvalidField = null;

    // Clear previous error styles
    document.querySelectorAll('.is-invalid').forEach(el => {
      el.classList.remove('is-invalid');
    });
    document.querySelectorAll('.invalid-feedback').forEach(el => {
      el.remove();
    });

    // Validate email
    if (emailInput && !emailInput.value.trim()) {
      isValid = false;
      emailInput.classList.add('is-invalid');
      addErrorFeedback(emailInput, 'Email is required.');
      if (!firstInvalidField) firstInvalidField = emailInput;
    } else if (emailInput && !isValidEmail(emailInput.value.trim())) {
      isValid = false;
      emailInput.classList.add('is-invalid');
      addErrorFeedback(emailInput, 'Please enter a valid email address.');
      if (!firstInvalidField) firstInvalidField = emailInput;
    }

    // Validate role
    if (roleSelect && !roleSelect.value) {
      isValid = false;
      roleSelect.classList.add('is-invalid');
      addErrorFeedback(roleSelect, 'Role is required.');
      if (!firstInvalidField) firstInvalidField = roleSelect;
    }

    if (!isValid) {
      e.preventDefault();
      if (firstInvalidField) {
        firstInvalidField.focus();
      }
    }
  });

  // Clear errors on input
  if (emailInput) {
    emailInput.addEventListener('input', () => {
      emailInput.classList.remove('is-invalid');
      const feedback = emailInput.parentElement.querySelector('.invalid-feedback');
      if (feedback) feedback.remove();
    });
  }

  if (roleSelect) {
    roleSelect.addEventListener('change', () => {
      roleSelect.classList.remove('is-invalid');
      const feedback = roleSelect.parentElement.querySelector('.invalid-feedback');
      if (feedback) feedback.remove();
    });
  }
};

const addErrorFeedback = (element, message) => {
  const feedback = document.createElement('div');
  feedback.className = 'invalid-feedback d-block';
  feedback.textContent = message;
  element.parentElement.appendChild(feedback);
};

const isValidEmail = (email) => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

const init = () => {
  initMemberAddForm();
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
