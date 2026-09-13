import java.util.Arrays;

class Identical {
    static double[] f0(double[] numbers) {
        double sum = 0;
        for (double num : numbers) {
            sum += num;
        }
        double mean = sum / numbers.length;

        double[] sortedNumbers = numbers.clone();
        Arrays.sort(sortedNumbers);

        double median;
        int length = sortedNumbers.length;
        if (length % 2 == 0) {
            median = (sortedNumbers[length / 2 - 1] + sortedNumbers[length / 2]) / 2.0;
        } else {
            median = sortedNumbers[length / 2];
        }

        return new double[] { mean, median };
    }

    static double[] f1(double[] numbers) {
        double sum = 0;
        for (double num : numbers) {
            sum += num;
        }
        double mean = sum / numbers.length;

        double[] sortedNumbers = numbers.clone();
        Arrays.sort(sortedNumbers);

        double median;
        int length = sortedNumbers.length;
        if (length % 2 == 0) {
            median = (sortedNumbers[length / 2 - 1] + sortedNumbers[length / 2]) / 2.0;
        } else {
            median = sortedNumbers[length / 2];
        }

        return new double[] { mean, median };
    }
}
