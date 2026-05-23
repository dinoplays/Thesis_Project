module confidence_computer #(
    parameter int unsigned IMAGE_DIM    = 128,
    parameter int unsigned IMAGE_DIM_BS = 7
)(
    input  wire                     clk,
    input  wire                     epi_valid_in,
    input  wire [7:0]               epi_column_in [0:8],
    input  wire [IMAGE_DIM_BS-1:0]  epi_column_idx_in,
    input  wire [IMAGE_DIM_BS-1:0]  epi_idx_in,
    input  wire                     orientation_in,

    output logic                    derivative_valid_out,
    output logic signed [10:0]      angular_derivative_column_out [0:6],
    output logic signed [10:0]      spatial_derivative_column_out [0:6],
    output logic [IMAGE_DIM_BS-1:0] derivative_row_idx_out,
    output logic [IMAGE_DIM_BS-1:0] derivative_column_idx_out,
    output logic                    derivative_orientation_out,

    output logic                    confidence_valid_out,
    output logic [9:0]              confidence_pixel_out,
    output logic [IMAGE_DIM_BS-1:0] confidence_row_idx_out,
    output logic [IMAGE_DIM_BS-1:0] confidence_column_idx_out,
    output logic                    confidence_orientation_out
);

    localparam int unsigned IMAGE_LAST_INT = IMAGE_DIM - 1;
    localparam logic [IMAGE_DIM_BS-1:0] LAST_VALID_PIXEL = IMAGE_LAST_INT[IMAGE_DIM_BS-1:0];

    // -------------------------------------------------------------------------
    // EPI column delay registers.
    //
    // At a cycle with current input column n:
    //   epi_column_in = column n
    //   epi_column_d1 = column n-1
    //   epi_column_d2 = column n-2
    //
    // The 3x3 derivative window is therefore centred on column n-1.
    // -------------------------------------------------------------------------
    logic [7:0] epi_column_d1 [0:8];
    logic [7:0] epi_column_d2 [0:8];

    logic                    valid_d1       = 1'b0;
    logic                    valid_d2       = 1'b0;
    logic [IMAGE_DIM_BS-1:0] column_idx_d1  = '0;
    logic [IMAGE_DIM_BS-1:0] column_idx_d2  = '0;
    logic [IMAGE_DIM_BS-1:0] epi_idx_d1     = '0;
    logic [IMAGE_DIM_BS-1:0] epi_idx_d2     = '0;
    logic                    orientation_d1 = 1'b0;
    logic                    orientation_d2 = 1'b0;

    integer i;

    // -------------------------------------------------------------------------
    // Helper functions
    // -------------------------------------------------------------------------

    function automatic logic signed [10:0] weighted_angular_derivative_q8_2(
        input logic [7:0] top_left,
        input logic [7:0] top_mid,
        input logic [7:0] top_right,
        input logic [7:0] bot_left,
        input logic [7:0] bot_mid,
        input logic [7:0] bot_right
    );
        logic signed [9:0] diff_left;
        logic signed [9:0] diff_mid;
        logic signed [9:0] diff_right;
        logic signed [11:0] total;
        begin
            // Angular derivative kernel:
            //
            // [  1/4   2/4   1/4 ]
            // [    0     0     0 ]
            // [ -1/4  -2/4  -1/4 ]
            //
            // The output is signed Q8.2, so the factor of four is kept:
            //
            // angular_q8_2 =
            //     (top_left - bot_left)
            //   + 2*(top_mid - bot_mid)
            //   +   (top_right - bot_right)
            //
            // This is centred on angular row k+1 and image/EPI column n-1.
            diff_left  = $signed({1'b0, top_left})  - $signed({1'b0, bot_left});
            diff_mid   = $signed({1'b0, top_mid})   - $signed({1'b0, bot_mid});
            diff_right = $signed({1'b0, top_right}) - $signed({1'b0, bot_right});

            total =
                {{2{diff_left[9]}}, diff_left} +
                ({{2{diff_mid[9]}}, diff_mid} <<< 1) +
                {{2{diff_right[9]}}, diff_right};

            weighted_angular_derivative_q8_2 = total[10:0];
        end
    endfunction

    function automatic logic signed [10:0] weighted_spatial_derivative_q8_2(
        input logic [7:0] left_top,
        input logic [7:0] left_mid,
        input logic [7:0] left_bot,
        input logic [7:0] right_top,
        input logic [7:0] right_mid,
        input logic [7:0] right_bot
    );
        logic signed [9:0] diff_top;
        logic signed [9:0] diff_mid;
        logic signed [9:0] diff_bot;
        logic signed [11:0] total;
        begin
            // Spatial derivative kernel:
            //
            // [  1/4    0   -1/4 ]
            // [  2/4    0   -2/4 ]
            // [  1/4    0   -1/4 ]
            //
            // The output is signed Q8.2, so the factor of four is kept:
            //
            // spatial_q8_2 =
            //     (left_top - right_top)
            //   + 2*(left_mid - right_mid)
            //   +   (left_bot - right_bot)
            //
            // This is centred on angular row k+1 and image/EPI column n-1.
            diff_top = $signed({1'b0, left_top}) - $signed({1'b0, right_top});
            diff_mid = $signed({1'b0, left_mid}) - $signed({1'b0, right_mid});
            diff_bot = $signed({1'b0, left_bot}) - $signed({1'b0, right_bot});

            total =
                {{2{diff_top[9]}}, diff_top} +
                ({{2{diff_mid[9]}}, diff_mid} <<< 1) +
                {{2{diff_bot[9]}}, diff_bot};

            weighted_spatial_derivative_q8_2 = total[10:0];
        end
    endfunction

    function automatic logic [10:0] abs11(
        input logic signed [10:0] x
    );
        begin
            if (x < 0) begin
                abs11 = $unsigned(-x);
            end
            else begin
                abs11 = $unsigned(x);
            end
        end
    endfunction

    function automatic logic [11:0] grad_mag_approx_q8_2(
        input logic signed [10:0] spatial_i,
        input logic signed [10:0] angular_i
    );
        logic [10:0] abs_spatial;
        logic [10:0] abs_angular;
        logic [10:0] max_abs;
        logic [10:0] min_abs;
        begin
            abs_spatial = abs11(spatial_i);
            abs_angular = abs11(angular_i);

            if (abs_spatial >= abs_angular) begin
                max_abs = abs_spatial;
                min_abs = abs_angular;
            end
            else begin
                max_abs = abs_angular;
                min_abs = abs_spatial;
            end

            // sqrt(a^2 + b^2) ~= max(|a|, |b|) + 3/8 min(|a|, |b|).
            // Inputs are Q8.2, so the output is also Q8.2.
            grad_mag_approx_q8_2 =
                {1'b0, max_abs} +
                {1'b0, (min_abs >> 2)} +
                {1'b0, (min_abs >> 3)};
        end
    endfunction

    function automatic logic [9:0] sat_u10_from_u15(
        input logic [14:0] x
    );
        begin
            if (x > 15'd1023) begin
                sat_u10_from_u15 = 10'h3FF;
            end
            else begin
                sat_u10_from_u15 = x[9:0];
            end
        end
    endfunction

    // -------------------------------------------------------------------------
    // Validity for a three-column window centred at column_idx_d1.
    //
    // A derivative output is valid only when the current input is column n, d1 is
    // column n-1, d2 is column n-2, and all three columns belong to the same EPI
    // and orientation.
    // -------------------------------------------------------------------------
    logic same_epi_window;
    logic centre_column_valid;

    always_comb begin
        same_epi_window =
            epi_valid_in &&
            valid_d1 &&
            valid_d2 &&
            (orientation_in == orientation_d1) &&
            (orientation_d1 == orientation_d2) &&
            (epi_idx_in == epi_idx_d1) &&
            (epi_idx_d1 == epi_idx_d2) &&
            (epi_column_idx_in == (column_idx_d1 + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1})) &&
            (column_idx_d1 == (column_idx_d2 + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1}));

        centre_column_valid =
            same_epi_window &&
            (column_idx_d1 != '0) &&
            (column_idx_d1 != LAST_VALID_PIXEL);
    end

    // -------------------------------------------------------------------------
    // Derivative stage.
    //
    // Timing optimisation:
    // - The derivative datapath registers are updated every clock cycle instead
    //   of being clock-enabled by centre_column_valid.
    // - Only derivative_valid_out is gated by centre_column_valid.
    //
    // This avoids putting the centre-column valid/window-detection logic on the
    // derivative arithmetic data path. Downstream stages must use the valid bit
    // to decide whether the registered derivative values are meaningful.
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Derivative_Stage
        derivative_valid_out       <= centre_column_valid;
        derivative_orientation_out <= orientation_d1;

        if (orientation_d1 == 1'b0) begin
            derivative_row_idx_out    <= epi_idx_d1;
            derivative_column_idx_out <= column_idx_d1;
        end
        else begin
            derivative_row_idx_out    <= column_idx_d1;
            derivative_column_idx_out <= epi_idx_d1;
        end

        // Outputs [0..6] correspond to angular centres [1..7].
        //
        // Spatial uses columns n-2 and n, centred at n-1:
        //   [d2, d1, in] = [left, centre, right]
        //
        // Angular uses rows k, k+1, k+2, centred at k+1, and is smoothed
        // across the same [d2, d1, in] spatial columns.
        angular_derivative_column_out[0] <= weighted_angular_derivative_q8_2(epi_column_d2[0], epi_column_d1[0], epi_column_in[0], epi_column_d2[2], epi_column_d1[2], epi_column_in[2]);
        angular_derivative_column_out[1] <= weighted_angular_derivative_q8_2(epi_column_d2[1], epi_column_d1[1], epi_column_in[1], epi_column_d2[3], epi_column_d1[3], epi_column_in[3]);
        angular_derivative_column_out[2] <= weighted_angular_derivative_q8_2(epi_column_d2[2], epi_column_d1[2], epi_column_in[2], epi_column_d2[4], epi_column_d1[4], epi_column_in[4]);
        angular_derivative_column_out[3] <= weighted_angular_derivative_q8_2(epi_column_d2[3], epi_column_d1[3], epi_column_in[3], epi_column_d2[5], epi_column_d1[5], epi_column_in[5]);
        angular_derivative_column_out[4] <= weighted_angular_derivative_q8_2(epi_column_d2[4], epi_column_d1[4], epi_column_in[4], epi_column_d2[6], epi_column_d1[6], epi_column_in[6]);
        angular_derivative_column_out[5] <= weighted_angular_derivative_q8_2(epi_column_d2[5], epi_column_d1[5], epi_column_in[5], epi_column_d2[7], epi_column_d1[7], epi_column_in[7]);
        angular_derivative_column_out[6] <= weighted_angular_derivative_q8_2(epi_column_d2[6], epi_column_d1[6], epi_column_in[6], epi_column_d2[8], epi_column_d1[8], epi_column_in[8]);

        spatial_derivative_column_out[0] <= weighted_spatial_derivative_q8_2(epi_column_d2[0], epi_column_d2[1], epi_column_d2[2], epi_column_in[0], epi_column_in[1], epi_column_in[2]);
        spatial_derivative_column_out[1] <= weighted_spatial_derivative_q8_2(epi_column_d2[1], epi_column_d2[2], epi_column_d2[3], epi_column_in[1], epi_column_in[2], epi_column_in[3]);
        spatial_derivative_column_out[2] <= weighted_spatial_derivative_q8_2(epi_column_d2[2], epi_column_d2[3], epi_column_d2[4], epi_column_in[2], epi_column_in[3], epi_column_in[4]);
        spatial_derivative_column_out[3] <= weighted_spatial_derivative_q8_2(epi_column_d2[3], epi_column_d2[4], epi_column_d2[5], epi_column_in[3], epi_column_in[4], epi_column_in[5]);
        spatial_derivative_column_out[4] <= weighted_spatial_derivative_q8_2(epi_column_d2[4], epi_column_d2[5], epi_column_d2[6], epi_column_in[4], epi_column_in[5], epi_column_in[6]);
        spatial_derivative_column_out[5] <= weighted_spatial_derivative_q8_2(epi_column_d2[5], epi_column_d2[6], epi_column_d2[7], epi_column_in[5], epi_column_in[6], epi_column_in[7]);
        spatial_derivative_column_out[6] <= weighted_spatial_derivative_q8_2(epi_column_d2[6], epi_column_d2[7], epi_column_d2[8], epi_column_in[6], epi_column_in[7], epi_column_in[8]);

        // Shift the EPI column history only when a valid EPI column arrives.
        //
        // Do not clear valid_d1/valid_d2 on invalid EPI bubbles. The EPI
        // compiler can insert invalid cycles between valid columns. Clearing
        // history on those bubbles breaks otherwise consecutive valid samples,
        // causing centre_column_valid to drop and leaving unwritten black pixels
        // in the confidence image. Boundary protection is still handled by
        // same_epi_window, which requires matching orientation, matching EPI
        // index, and consecutive column indices.
        if (epi_valid_in) begin
            for (i = 0; i < 9; i = i + 1) begin
                epi_column_d2[i] <= epi_column_d1[i];
                epi_column_d1[i] <= epi_column_in[i];
            end

            valid_d2       <= valid_d1;
            valid_d1       <= 1'b1;
            column_idx_d2  <= column_idx_d1;
            column_idx_d1  <= epi_column_idx_in;
            epi_idx_d2     <= epi_idx_d1;
            epi_idx_d1     <= epi_idx_in;
            orientation_d2 <= orientation_d1;
            orientation_d1 <= orientation_in;
        end
    end

    // -------------------------------------------------------------------------
    // Confidence stage.
    //
    // The confidence arithmetic consumes the registered derivative outputs from
    // the previous cycle. Therefore the metadata path is delayed by three cycles:
    //
    //   C0 derivative output register
    //   C1 magnitude register
    //   C2 magnitude sum register
    //   C3 average register
    //   C4 confidence output register
    //
    // In this always_ff block, reading derivative_valid_out gives the previous
    // cycle's derivative metadata, which matches the derivative data consumed
    // by mag_0..mag_6.
    // -------------------------------------------------------------------------
    logic [11:0] mag_0 = '0;
    logic [11:0] mag_1 = '0;
    logic [11:0] mag_2 = '0;
    logic [11:0] mag_3 = '0;
    logic [11:0] mag_4 = '0;
    logic [11:0] mag_5 = '0;
    logic [11:0] mag_6 = '0;

    logic [14:0] mag_sum = '0;
    logic [14:0] confidence_avg_approx = '0;

    logic                    conf_meta_valid_0       = 1'b0;
    logic                    conf_meta_valid_1       = 1'b0;
    logic                    conf_meta_valid_2       = 1'b0;
    logic [IMAGE_DIM_BS-1:0] conf_meta_row_idx_0     = '0;
    logic [IMAGE_DIM_BS-1:0] conf_meta_row_idx_1     = '0;
    logic [IMAGE_DIM_BS-1:0] conf_meta_row_idx_2     = '0;
    logic [IMAGE_DIM_BS-1:0] conf_meta_column_idx_0  = '0;
    logic [IMAGE_DIM_BS-1:0] conf_meta_column_idx_1  = '0;
    logic [IMAGE_DIM_BS-1:0] conf_meta_column_idx_2  = '0;
    logic                    conf_meta_orientation_0 = 1'b0;
    logic                    conf_meta_orientation_1 = 1'b0;
    logic                    conf_meta_orientation_2 = 1'b0;

    always_ff @(posedge clk) begin : Confidence_Stage
        mag_0 <= grad_mag_approx_q8_2(spatial_derivative_column_out[0], angular_derivative_column_out[0]);
        mag_1 <= grad_mag_approx_q8_2(spatial_derivative_column_out[1], angular_derivative_column_out[1]);
        mag_2 <= grad_mag_approx_q8_2(spatial_derivative_column_out[2], angular_derivative_column_out[2]);
        mag_3 <= grad_mag_approx_q8_2(spatial_derivative_column_out[3], angular_derivative_column_out[3]);
        mag_4 <= grad_mag_approx_q8_2(spatial_derivative_column_out[4], angular_derivative_column_out[4]);
        mag_5 <= grad_mag_approx_q8_2(spatial_derivative_column_out[5], angular_derivative_column_out[5]);
        mag_6 <= grad_mag_approx_q8_2(spatial_derivative_column_out[6], angular_derivative_column_out[6]);

        mag_sum <=
            {3'b000, mag_0} +
            {3'b000, mag_1} +
            {3'b000, mag_2} +
            {3'b000, mag_3} +
            {3'b000, mag_4} +
            {3'b000, mag_5} +
            {3'b000, mag_6};

        // Approximate /7 as /8 + /64 + 1. This matches the old shift-only style.
        // mag_sum is already in Q8.2, so the average remains Q8.2.
        confidence_avg_approx <= (mag_sum >> 3) + (mag_sum >> 6) + 15'd1;

        conf_meta_valid_0       <= derivative_valid_out;
        conf_meta_valid_1       <= conf_meta_valid_0;
        conf_meta_valid_2       <= conf_meta_valid_1;

        conf_meta_row_idx_0     <= derivative_row_idx_out;
        conf_meta_row_idx_1     <= conf_meta_row_idx_0;
        conf_meta_row_idx_2     <= conf_meta_row_idx_1;

        conf_meta_column_idx_0  <= derivative_column_idx_out;
        conf_meta_column_idx_1  <= conf_meta_column_idx_0;
        conf_meta_column_idx_2  <= conf_meta_column_idx_1;

        conf_meta_orientation_0 <= derivative_orientation_out;
        conf_meta_orientation_1 <= conf_meta_orientation_0;
        conf_meta_orientation_2 <= conf_meta_orientation_1;

        confidence_valid_out       <= conf_meta_valid_2;
        confidence_row_idx_out     <= conf_meta_row_idx_2;
        confidence_column_idx_out  <= conf_meta_column_idx_2;
        confidence_orientation_out <= conf_meta_orientation_2;
        confidence_pixel_out       <= sat_u10_from_u15(confidence_avg_approx);
    end

endmodule