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
package org.sonar.ce.task.projectanalysis.history;

import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.sonar.ce.task.step.ComputationStep;
import org.sonar.db.DbClient;
import org.sonar.db.DbSession;
import org.sonar.db.property.PropertyDto;
import org.sonarsource.history.server.service.HistoryPurgeService;

import static org.sonar.core.config.PurgeConstants.DAYS_BEFORE_DELETING_HISTORY;
import static org.sonar.core.config.PurgeProperties.DEFAULT_HISTORY_MAX_AGE_IN_DAYS;

public final class HistoryPurgeStep implements ComputationStep {
  private static final Logger LOG = LoggerFactory.getLogger(HistoryPurgeStep.class);

  private final HistoryPurgeService historyPurgeService;
  private final DbClient dbClient;
  private final Clock clock;

  public HistoryPurgeStep(
    HistoryPurgeService historyPurgeService,
    DbClient dbClient,
    Clock clock) {
    this.historyPurgeService = historyPurgeService;
    this.dbClient = dbClient;
    this.clock = clock;
  }

  @Override
  public void execute(Context context) {
    LOG.info("Purging history");
    LocalDate thresholdDate = getThresholdDate();
    historyPurgeService.purgeHistoryBefore(thresholdDate);
  }

  private LocalDate getThresholdDate() {
    try (DbSession dbSession = dbClient.openSession(false)) {
      int thresholdDays = Optional.ofNullable(dbClient.propertiesDao()
        .selectGlobalProperty(dbSession, DAYS_BEFORE_DELETING_HISTORY))
        .map(HistoryPurgeStep::getDaysFromProperty)
        .orElse(DEFAULT_HISTORY_MAX_AGE_IN_DAYS);
      LocalDate today = LocalDate.from(clock.instant().atZone(ZoneOffset.UTC));
      return today.minusDays(thresholdDays);
    }
  }

  private static int getDaysFromProperty(PropertyDto propertyDto) {
    try {
      return Integer.parseInt(propertyDto.getValue());
    } catch (NumberFormatException e) {
      LOG.error("Error parsing integer property {}; falling back to default value: {}", propertyDto, DEFAULT_HISTORY_MAX_AGE_IN_DAYS, e);
      return DEFAULT_HISTORY_MAX_AGE_IN_DAYS;
    }
  }

  @Override
  public String getDescription() {
    return "Purge History";
  }
}
