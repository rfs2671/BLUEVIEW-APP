/** The app's one tile-viewer API client: same base URL and token store as the rest of the app. */
import { getToken } from '../utils/api';
import { createSheetApi } from './sheetApi';

export const API_BASE = process.env.EXPO_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_URL || 'https://api.levelog.com';

export const sheetApi = createSheetApi({ apiBase: API_BASE, getToken });
export default sheetApi;
