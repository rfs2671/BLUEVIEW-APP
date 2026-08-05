import { useState } from 'react';
import { projectsAPI } from '../utils/api';

export function useProjects() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);

  // Create project
  const createProject = async (projectData) => {
    return await projectsAPI.create(projectData);
  };

  // Update project
  const updateProject = async (projectId, updates) => {
    return await projectsAPI.update(projectId, updates);
  };

  // Delete project
  const deleteProject = async (projectId) => {
    return await projectsAPI.delete(projectId);
  };

  // Get project by ID
  const getProjectById = async (projectId) => {
    try {
      return await projectsAPI.getById(projectId);
    } catch (error) {
      console.error('Project not found:', error);
      return null;
    }
  };

  // Get active projects
  const getActiveProjects = async () => {
    try {
      const all = await projectsAPI.getAll();
      return (all || []).filter(p => (p.status || 'active') === 'active');
    } catch (error) {
      console.error('Failed to fetch active projects:', error);
      return [];
    }
  };

  return {
    projects,
    loading,
    createProject,
    updateProject,
    deleteProject,
    getProjectById,
    getActiveProjects,
  };
}
