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
package org.sonar.server.platform.db.migration.version.v202605;

import java.sql.SQLException;
import java.sql.Types;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.sonar.db.MigrationDbTester;

import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.COLUMN_DIMENSION_HASH;
import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.COLUMN_ID;
import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.COLUMN_SEVERITY;
import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.COLUMN_STATUS;
import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.DIMENSION_HASH_SIZE;
import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.INDEX_DIMENSION_HASH;
import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.SEVERITY_SIZE;
import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.STATUS_SIZE;
import static org.sonar.server.platform.db.migration.version.v202605.CreateScaIssueDimensionsTable.TABLE_NAME;

class CreateScaIssueDimensionsTableTest {

  @RegisterExtension
  public final MigrationDbTester db = MigrationDbTester.createForMigrationStep(CreateScaIssueDimensionsTable.class);

  private final CreateScaIssueDimensionsTable underTest = new CreateScaIssueDimensionsTable(db.database());

  @Test
  void migration_should_create_table() throws SQLException {
    db.assertTableDoesNotExist(TABLE_NAME);

    underTest.execute();

    db.assertTableExists(TABLE_NAME);
    db.assertPrimaryKey(TABLE_NAME, "pk_sca_issue_dimensions", COLUMN_ID);
    db.assertColumnDefinition(TABLE_NAME, COLUMN_ID, Types.INTEGER, null, false);
    db.assertColumnDefinition(TABLE_NAME, COLUMN_DIMENSION_HASH, Types.VARCHAR, DIMENSION_HASH_SIZE, false);
    db.assertColumnDefinition(TABLE_NAME, COLUMN_SEVERITY, Types.VARCHAR, SEVERITY_SIZE, false);
    db.assertColumnDefinition(TABLE_NAME, COLUMN_STATUS, Types.VARCHAR, STATUS_SIZE, true);
    db.assertUniqueIndex(TABLE_NAME, INDEX_DIMENSION_HASH, COLUMN_DIMENSION_HASH);
  }

  @Test
  void migration_should_be_reentrant() throws SQLException {
    db.assertTableDoesNotExist(TABLE_NAME);

    underTest.execute();
    underTest.execute();

    db.assertTableExists(TABLE_NAME);
  }
}
