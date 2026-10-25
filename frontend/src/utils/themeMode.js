// Which theme is DRAWN, as opposed to which one the person chose. A forced mode (a site device account is held to
// light) wins over the stored choice, and releasing it returns to that choice untouched.
export const effectiveIsDark = (userIsDark, forced) => (forced ? forced === 'dark' : !!userIsDark);
