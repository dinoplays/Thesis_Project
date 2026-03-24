module bit_shift_low_pass_filter #(
    parameter int unsigned IMAGE_DIM    = 128,
    parameter int unsigned IMAGE_DIM_BS = 7
)(
    input  wire         clk,
    input  wire         pixel_valid_in,
    input  wire         soc_in,
    input  wire         eoc_in,
    input  wire         solf_in,
    input  wire         eolf_in,
    input  wire  [7:0]  pixel_in,
    output logic        pixel_valid_out,
    output logic        soc_out,
    output logic        eoc_out,
    output logic        solf_out,
    output logic        eolf_out,
    output logic [14:0] pixel_out
);

    // -------------------------------------------------------------------------
    // 7x7 low-pass kernel
    // Sum = 128, so output remains unsigned Q8.7
    // -------------------------------------------------------------------------
    localparam logic [1:0] kernel_7 [0:48] = '{
        0, 0, 1, 1, 1, 0, 0,
        0, 1, 2, 2, 2, 1, 0,
        1, 2, 2, 2, 2, 2, 1,
        1, 2, 2, 2, 2, 2, 1,
        1, 2, 2, 2, 2, 2, 1,
        0, 1, 2, 2, 2, 1, 0,
        0, 0, 1, 1, 1, 0, 0
    };

    localparam int unsigned BUFFER_LAST     = (6 << IMAGE_DIM_BS) + 6;
    localparam int unsigned LAG_BUFFER_MAX  = BUFFER_LAST;
    localparam int unsigned LAG_BUFFER_SIZE = $clog2(LAG_BUFFER_MAX + 1);

    // -------------------------------------------------------------------------
    // LF flags
    // -------------------------------------------------------------------------
    logic next_soc_is_solf = 1'b0;
    logic next_eoc_is_eolf = 1'b0;

    // -------------------------------------------------------------------------
    // Pixel buffer
    // Index 0 = oldest pixel, BUFFER_LAST = newest pixel
    // -------------------------------------------------------------------------
    logic [7:0] pixel_buffer [0:BUFFER_LAST];

    // -------------------------------------------------------------------------
    // Input counters and lag flags
    // -------------------------------------------------------------------------
    logic [IMAGE_DIM_BS-1:0] row_in_count    = '0;
    logic [IMAGE_DIM_BS-1:0] column_in_count = '0;

    // These counters intentionally keep the SAME semantics as the working
    // non-pipelined version: they represent the stage-0 output position used
    // for blur/raw selection before the counter update in that same cycle.
    logic [IMAGE_DIM_BS-1:0] row_out_count    = '0;
    logic [IMAGE_DIM_BS-1:0] column_out_count = '0;

    logic [LAG_BUFFER_SIZE-2:0] start_lag_buffer_count = '0;
    logic [LAG_BUFFER_SIZE-1:0] end_lag_buffer_count   = '0;

    logic soc_lag_flag  = 1'b0;
    logic eoc_lag_flag  = 1'b0;
    logic soc_out_pulse = 1'b0;
    logic eoc_out_pulse = 1'b0;

    // -------------------------------------------------------------------------
    // Stage-0 control signals
    // These match the working non-pipelined logic exactly.
    // -------------------------------------------------------------------------
    logic output_valid_now;
    logic soc_now;
    logic eoc_now;
    logic solf_now;
    logic eolf_now;
    logic output_step_now;
    logic is_convolved_now;

    assign output_valid_now =
        ((soc_lag_flag && pixel_valid_in) ||
         (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)));

    assign soc_now =
        ((soc_lag_flag && pixel_valid_in) && soc_out_pulse);

    assign eoc_now =
        ((eoc_lag_flag) &&
         (eoc_out_pulse) &&
         ((((column_in_count != '0) && pixel_valid_in) || (column_in_count == '0))));

    assign solf_now = (next_soc_is_solf && soc_now);
    assign eolf_now = (next_eoc_is_eolf && eoc_now);

    assign output_step_now =
        ((soc_lag_flag && pixel_valid_in && (!soc_out_pulse)) ||
         (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)));

    // -------------------------------------------------------------------------
    // EXACT same 7x7 edge selection logic as the working non-pipelined code.
    // Do NOT "predict" the next coordinate here.
    // -------------------------------------------------------------------------
    assign is_convolved_now =
        !(
            (row_out_count < 3) ||
            (row_out_count >= IMAGE_DIM - 3) ||
            ((row_out_count == IMAGE_DIM - 4) && (column_out_count == IMAGE_DIM - 1)) ||
            (column_out_count >= IMAGE_DIM - 5) ||
            (column_out_count == '0)
         );

    // -------------------------------------------------------------------------
    // Combinational partial sums
    // Stage 0:
    //   sum012_s0 <= rows 0,1,2
    //   sum3_s0   <= row 3
    //   sum4_s0   <= row 4
    //   sum56_s0  <= rows 5,6
    //
    // Stage 1:
    //   sum34_s1  <= sum3_s0 + sum4_s0
    //   sum012_s1 <= sum012_s0
    //   sum56_s1  <= sum56_s0
    //
    // Stage 2:
    //   sum014_s2 <= sum012_s1 + sum34_s1
    //
    // Stage 3:
    //   final add/select
    // -------------------------------------------------------------------------
    logic [14:0] sum_row012_comb;
    logic [14:0] sum_row3_comb;
    logic [14:0] sum_row4_comb;
    logic [14:0] sum_row56_comb;
    logic [14:0] raw_center_comb;

    integer r_idx;
    integer c_idx;
    integer k_idx;

    always_comb begin
        sum_row012_comb = 15'd0;
        sum_row3_comb   = 15'd0;
        sum_row4_comb   = 15'd0;
        sum_row56_comb  = 15'd0;

        // Rows 0,1,2
        for (r_idx = 0; r_idx < 3; r_idx = r_idx + 1) begin
            for (c_idx = 0; c_idx < 7; c_idx = c_idx + 1) begin
                k_idx = (r_idx * 7) + c_idx;
                sum_row012_comb = sum_row012_comb
                                + (pixel_buffer[(r_idx << IMAGE_DIM_BS) + c_idx] << kernel_7[k_idx]);
            end
        end

        // Row 3 only
        for (c_idx = 0; c_idx < 7; c_idx = c_idx + 1) begin
            k_idx = (3 * 7) + c_idx;
            sum_row3_comb = sum_row3_comb
                          + (pixel_buffer[(3 << IMAGE_DIM_BS) + c_idx] << kernel_7[k_idx]);
        end

        // Row 4 only
        for (c_idx = 0; c_idx < 7; c_idx = c_idx + 1) begin
            k_idx = (4 * 7) + c_idx;
            sum_row4_comb = sum_row4_comb
                          + (pixel_buffer[(4 << IMAGE_DIM_BS) + c_idx] << kernel_7[k_idx]);
        end

        // Rows 5,6
        for (r_idx = 5; r_idx < 7; r_idx = r_idx + 1) begin
            for (c_idx = 0; c_idx < 7; c_idx = c_idx + 1) begin
                k_idx = (r_idx * 7) + c_idx;
                sum_row56_comb = sum_row56_comb
                               + (pixel_buffer[(r_idx << IMAGE_DIM_BS) + c_idx] << kernel_7[k_idx]);
            end
        end

        // Raw centre pixel in Q8.7
        raw_center_comb = {pixel_buffer[(3 << IMAGE_DIM_BS) + 3], 7'd0};
    end

    // -------------------------------------------------------------------------
    // Pipeline registers
    // -------------------------------------------------------------------------
    // Stage 0
    logic        valid_s0 = 1'b0;
    logic        soc_s0   = 1'b0;
    logic        eoc_s0   = 1'b0;
    logic        solf_s0  = 1'b0;
    logic        eolf_s0  = 1'b0;
    logic        conv_s0  = 1'b0;

    logic [14:0] sum012_s0 = 15'd0;
    logic [14:0] sum3_s0   = 15'd0;
    logic [14:0] sum4_s0   = 15'd0;
    logic [14:0] sum56_s0  = 15'd0;
    logic [14:0] raw_s0    = 15'd0;

    // Stage 1
    logic        valid_s1 = 1'b0;
    logic        soc_s1   = 1'b0;
    logic        eoc_s1   = 1'b0;
    logic        solf_s1  = 1'b0;
    logic        eolf_s1  = 1'b0;
    logic        conv_s1  = 1'b0;

    logic [14:0] sum012_s1 = 15'd0;
    logic [14:0] sum34_s1  = 15'd0;
    logic [14:0] sum56_s1  = 15'd0;
    logic [14:0] raw_s1    = 15'd0;

    // Stage 2
    logic        valid_s2 = 1'b0;
    logic        soc_s2   = 1'b0;
    logic        eoc_s2   = 1'b0;
    logic        solf_s2  = 1'b0;
    logic        eolf_s2  = 1'b0;
    logic        conv_s2  = 1'b0;

    logic [14:0] sum014_s2 = 15'd0;
    logic [14:0] sum56_s2  = 15'd0;
    logic [14:0] raw_s2    = 15'd0;

    // Stage 3 / final
    logic        valid_s3 = 1'b0;
    logic        soc_s3   = 1'b0;
    logic        eoc_s3   = 1'b0;
    logic        solf_s3  = 1'b0;
    logic        eolf_s3  = 1'b0;

    logic [14:0] pixel_s3 = 15'd0;

    // -------------------------------------------------------------------------
    // Image buffer / lag logic
    // Keep timing decisions aligned to STAGE-0 launch timing.
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Image_Buffer
        if (soc_in) begin
            row_in_count           <= '0;
            column_in_count        <= '0;
            soc_lag_flag           <= 1'b0;
            start_lag_buffer_count <= {{(LAG_BUFFER_SIZE-2){1'b0}}, 1'b1};
        end

        if (eoc_in) begin
            eoc_lag_flag    <= 1'b1;
            row_in_count    <= '0;
            column_in_count <= '0;
        end

        // Match original behavior to the logical start of output stream,
        // not the delayed external pulse.
        if (soc_now) begin
            end_lag_buffer_count <= '0;
        end

        // Clear state once the logical end-of-light-field output is launched
        // into the pipeline.
        if (eolf_now) begin
            row_in_count           <= '0;
            column_in_count        <= '0;
            start_lag_buffer_count <= '0;
            end_lag_buffer_count   <= '0;
            soc_lag_flag           <= 1'b0;
            eoc_lag_flag           <= 1'b0;
            soc_out_pulse          <= 1'b0;
            eoc_out_pulse          <= 1'b0;
        end

        if (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)) begin
            end_lag_buffer_count <= end_lag_buffer_count + {{(LAG_BUFFER_SIZE-1){1'b0}}, 1'b1};

            if (end_lag_buffer_count == (3 << IMAGE_DIM_BS) + 2) begin
                eoc_out_pulse <= 1'b1;
            end

            if (end_lag_buffer_count == (3 << IMAGE_DIM_BS) + 3) begin
                eoc_lag_flag <= 1'b0;
            end
        end

        if (pixel_valid_in || (eoc_lag_flag && (row_in_count == '0) && (column_in_count == '0))) begin
            for (int idx = 0; idx < BUFFER_LAST; idx++) begin
                pixel_buffer[idx] <= pixel_buffer[idx + 1];
            end

            if (pixel_valid_in) begin
                pixel_buffer[BUFFER_LAST] <= pixel_in;

                if (!soc_lag_flag) begin
                    start_lag_buffer_count <= start_lag_buffer_count + {{(LAG_BUFFER_SIZE-2){1'b0}}, 1'b1};

                    if (start_lag_buffer_count == (3 << IMAGE_DIM_BS) + 3) begin
                        soc_lag_flag  <= 1'b1;
                        soc_out_pulse <= 1'b1;
                    end
                end

                if (column_in_count == IMAGE_DIM - 1) begin
                    column_in_count <= '0;
                    row_in_count    <= row_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
                end
                else begin
                    column_in_count <= column_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
                end
            end
        end

        if (soc_out_pulse && pixel_valid_in) begin
            soc_out_pulse <= 1'b0;
        end

        if (eoc_out_pulse && ((((column_in_count != '0) && pixel_valid_in) || (column_in_count == '0)))) begin
            eoc_out_pulse <= 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // 4-stage convolution pipeline
    // Control is generated with working stage-0 timing, then delayed to match
    // the datapath.
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Convolution_Pipeline
        // Set LF flags from input side
        if (solf_in) begin
            next_soc_is_solf <= 1'b1;
        end

        if (eolf_in) begin
            next_eoc_is_eolf <= 1'b1;
        end

        // Clear LF flags when the logical stage-0 launch occurs
        if (solf_now) begin
            next_soc_is_solf <= 1'b0;
        end

        if (eolf_now) begin
            next_eoc_is_eolf <= 1'b0;
        end

        // -----------------------------
        // Stage 0 capture
        // -----------------------------
        valid_s0 <= output_valid_now;
        soc_s0   <= soc_now;
        eoc_s0   <= eoc_now;
        solf_s0  <= solf_now;
        eolf_s0  <= eolf_now;
        conv_s0  <= is_convolved_now;

        sum012_s0 <= sum_row012_comb;
        sum3_s0   <= sum_row3_comb;
        sum4_s0   <= sum_row4_comb;
        sum56_s0  <= sum_row56_comb;
        raw_s0    <= raw_center_comb;

        // -----------------------------
        // Stage 1
        // sum34_s1 <= sum3_s0 + sum4_s0
        // sum012_s1 <= sum012_s0
        // sum56_s1 <= sum56_s0
        // -----------------------------
        valid_s1 <= valid_s0;
        soc_s1   <= soc_s0;
        eoc_s1   <= eoc_s0;
        solf_s1  <= solf_s0;
        eolf_s1  <= eolf_s0;
        conv_s1  <= conv_s0;

        sum012_s1 <= sum012_s0;
        sum34_s1  <= sum3_s0 + sum4_s0;
        sum56_s1  <= sum56_s0;
        raw_s1    <= raw_s0;

        // -----------------------------
        // Stage 2
        // sum014_s2 <= sum012_s1 + sum34_s1
        // -----------------------------
        valid_s2 <= valid_s1;
        soc_s2   <= soc_s1;
        eoc_s2   <= eoc_s1;
        solf_s2  <= solf_s1;
        eolf_s2  <= eolf_s1;
        conv_s2  <= conv_s1;

        sum014_s2 <= sum012_s1 + sum34_s1;
        sum56_s2  <= sum56_s1;
        raw_s2    <= raw_s1;

        // -----------------------------
        // Stage 3 / final
        // final add/select
        // -----------------------------
        valid_s3 <= valid_s2;
        soc_s3   <= soc_s2;
        eoc_s3   <= eoc_s2;
        solf_s3  <= solf_s2;
        eolf_s3  <= eolf_s2;

        if (conv_s2) begin
            pixel_s3 <= sum014_s2 + sum56_s2;
        end
        else begin
            pixel_s3 <= raw_s2;
        end

        // -----------------------------------------------------------------
        // Final delayed outputs
        // -----------------------------------------------------------------
        pixel_valid_out <= valid_s3;
        soc_out         <= soc_s3;
        eoc_out         <= eoc_s3;
        solf_out        <= solf_s3;
        eolf_out        <= eolf_s3;
        pixel_out       <= pixel_s3;

        // -----------------------------------------------------------------
        // Stage-0 output coordinate tracking
        // This intentionally matches the working code:
        // - decide using current row_out_count / column_out_count
        // - then update the counters afterward in the same clock
        // -----------------------------------------------------------------
        if (eoc_now) begin
            row_out_count    <= '0;
            column_out_count <= '0;
        end
        else if (output_step_now) begin
            if (column_out_count == IMAGE_DIM - 1) begin
                column_out_count <= '0;
                row_out_count    <= row_out_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
            end
            else begin
                column_out_count <= column_out_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
            end
        end
    end

endmodule