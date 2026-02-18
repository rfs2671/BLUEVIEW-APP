// Web stub - app uses API directly on web
const database = {
  get: () => ({ query: () => ({ fetch: async () => [] }) }),
  write: async (fn) => fn(),
};

export default database;
