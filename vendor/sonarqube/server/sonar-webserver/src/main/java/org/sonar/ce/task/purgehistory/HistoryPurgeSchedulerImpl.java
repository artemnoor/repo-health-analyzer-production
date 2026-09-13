/*
 * SonarQube
 * Copyright (C) SonarSource Sàrl
 * mailto:info AT sonarsource DOT com
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 3 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this program; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
 */
package org.sonar.ce.task.purgehistory;

import java.util.concurrent.TimeUnit;
import org.sonar.ce.queue.CeQueue;
import org.sonar.server.util.GlobalLockManager;

public class HistoryPurgeSchedulerImpl implements HistoryPurgeScheduler {
  static final long INITIAL_DELAY_IN_HOURS = 0;
  static final long ENQUEUE_DELAY_IN_HOURS = 24;

  private final HistoryPurgeExecutorService executorService;
  private final HistoryPurgeTaskLimiter historyPurgeTaskLimiter;

  public HistoryPurgeSchedulerImpl(HistoryPurgeExecutorService executorService, CeQueue ceQueue,
    GlobalLockManager lockManager) {
    this.executorService = executorService;
    this.historyPurgeTaskLimiter = new HistoryPurgeTaskLimiter(ceQueue, lockManager);
  }

  @Override
  public void startScheduling() {
    executorService.scheduleAtFixedRate(historyPurgeTaskLimiter::tryEnqueue, INITIAL_DELAY_IN_HOURS, ENQUEUE_DELAY_IN_HOURS, TimeUnit.HOURS);
  }


}
