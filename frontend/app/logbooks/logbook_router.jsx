/**
 * frontend/app/logbooks/[type].jsx
 *
 * Dynamic router — maps log_type param to the correct log form component.
 * Route: /logbooks/scaffold_maintenance?projectId=xxx&date=2025-01-15
 *         /logbooks/toolbox_talk?...
 *         /logbooks/preshift_signin?...
 *         /logbooks/subcontractor_orientation?...
 *         /logbooks/osha_log?...
 *         /logbooks/daily_jobsite?...
 */
import { useLocalSearchParams } from 'expo-router';

import ScaffoldMaintenanceLog from './scaffold_maintenance';
import ToolboxTalkLog from './toolbox_talk';
import PreShiftSignIn from './preshift_signin';
import SubcontractorOrientation from './subcontractor_orientation';
import OshaLogBook from './osha_log';
import DailyJobsiteLog from './daily_jobsite';

const LOG_COMPONENTS = {
  scaffold_maintenance: ScaffoldMaintenanceLog,
  toolbox_talk: ToolboxTalkLog,
  preshift_signin: PreShiftSignIn,
  subcontractor_orientation: SubcontractorOrientation,
  osha_log: OshaLogBook,
  daily_jobsite: DailyJobsiteLog,
};

export default function LogBookRouter() {
  const { type } = useLocalSearchParams();
  const Component = LOG_COMPONENTS[type];

  if (!Component) {
    return null; // or a 404 screen
  }

  return <Component />;
}
