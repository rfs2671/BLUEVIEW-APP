import { useState, useEffect } from 'react';
import { Q } from '@nozbe/watermelondb';
import database from '../database';

export function useProjects() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);

  // Create project
  const createProject = async (projectData) => {
    await database.write(async () => {
      await database.get('projects').create(project => {
        project.name = projectData.name;
        project.address = projectData.address || '';
        project.status = projectData.status || 'active';
        project.startDate = projectData.start_date ? new Date(projectData.start_date).getTime() : Date.now();
        project.endDate = projectData.end_date ? new Date(projectData.end_date).getTime() : null;
        project.backendId = projectData._id || '';
        project.isDeleted = false;
      });
    });
  };

  // Update project
  const updateProject = async (projectId, updates) => {
    await database.write(async () => {
      const project = await database.get('projects').find(projectId);
      await project.update(p => {
        if (updates.name !== undefined) p.name = updates.name;
        if (updates.address !== undefined) p.address = updates.address;
        if (updates.status !== undefined) p.status = updates.status;
        if (updates.start_date !== undefined) {
          p.startDate = new Date(updates.start_date).getTime();
        }
        if (updates.end_date !== undefined) {
          p.endDate = updates.end_date ? new Date(updates.end_date).getTime() : null;
        }
      });
    });
  };

  // Delete project (soft delete)
  const deleteProject = async (projectId) => {
    await database.write(async () => {
      const project = await database.get('projects').find(projectId);
      await project.update(p => {
        p.isDeleted = true;
      });
    });
  };

  // Get project by ID
  const getProjectById = async (projectId) => {
  try {
    return await database.get('projects').find(projectId);
  } catch (error) {
    try {
      const results = await database.get('projects')
        .query(Q.where('backend_id', projectId))
        .fetch();
      if (results.length > 0) return results[0];
    } catch (e) {
    }
    try {
      const { projectsAPI } = require('../utils/api');
      return await projectsAPI.getById(projectId);
    } catch (e) {
      console.error('Project not found anywhere:', e);
      return null;
      }
    }
  };
 
  // Get active projects
  const getActiveProjects = async () => {
    return await database.get('projects')
      .query(
        Q.where('is_deleted', false),
        Q.where('status', 'active')
      )
      .fetch();
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
