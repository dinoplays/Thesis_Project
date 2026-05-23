module low_pass_filter #(
    parameter int unsigned IMAGE_DIM    = 128
)(
    input  wire                          clk,
    input  wire                          solf_in,
    input  wire                          eolf_in,
    input  wire                          pixel_valid_in,
    input  wire [$clog2(IMAGE_DIM)-1:0] row_idx_in,
    input  wire [$clog2(IMAGE_DIM)-1:0] column_idx_in,
    input  wire [9:0]                   confidence_in,
    input  wire signed [15:0]            disparity_in,

    output logic                         solf_out,
    output logic                         eolf_out,
    output logic                         pixel_valid_out,
    output logic [$clog2(IMAGE_DIM)-1:0] row_idx_out,
    output logic [$clog2(IMAGE_DIM)-1:0] column_idx_out,
    output logic [9:0]                   confidence_out,
    output logic signed [15:0]           disparity_out
);

    // -------------------------------------------------------------------------
    // Final-stage 7x7 low-pass filter.
    //
    // The input stream from fused_aligned_output is still row-major, but it is
    // not a full 128-pixel-wide row. It is an interior stream where each row
    // starts 4 pixels in and ends 4 pixels early:
    //
    //   input columns/rows used by this module: 4..123
    //   effective row width in the compact stream: 128 - 8 = 120
    //
    // A compact valid-only shift register is therefore still correct, but the
    // row stride used to address the 7x7 taps must be 120, not 128. Using the
    // full IMAGE_DIM stride makes each tap row jump too far through the compact
    // stream, causing diagonal/streaked blur artefacts.
    //
    // The 7x7 kernel then removes 3 pixels from the already-interior stream:
    //
    //   output rows/columns: 7..120
    //
    // Output widths are preserved:
    //   confidence: unsigned 10-bit Q8.2
    //   disparity:  signed   16-bit Q8.8
    // -------------------------------------------------------------------------

    localparam int unsigned INPUT_MARGIN        = 4;
    localparam int unsigned KERNEL_RADIUS       = 3;
    localparam int unsigned EFFECTIVE_ROW_PIXELS = IMAGE_DIM - (2 * INPUT_MARGIN);

    localparam int unsigned FIRST_INPUT_INT     = INPUT_MARGIN;
    localparam int unsigned LAST_INPUT_INT      = IMAGE_DIM - INPUT_MARGIN - 1;
    localparam int unsigned FIRST_OUTPUT_INT    = INPUT_MARGIN + KERNEL_RADIUS;
    localparam int unsigned LAST_OUTPUT_INT     = IMAGE_DIM - INPUT_MARGIN - KERNEL_RADIUS - 1;

    localparam logic [$clog2(IMAGE_DIM)-1:0] FIRST_INPUT_PIXEL  = FIRST_INPUT_INT[$clog2(IMAGE_DIM)-1:0];
    localparam logic [$clog2(IMAGE_DIM)-1:0] LAST_INPUT_PIXEL   = LAST_INPUT_INT[$clog2(IMAGE_DIM)-1:0];
    localparam logic [$clog2(IMAGE_DIM)-1:0] FIRST_OUTPUT_PIXEL = FIRST_OUTPUT_INT[$clog2(IMAGE_DIM)-1:0];
    localparam logic [$clog2(IMAGE_DIM)-1:0] LAST_OUTPUT_PIXEL  = LAST_OUTPUT_INT[$clog2(IMAGE_DIM)-1:0];

    localparam int unsigned BUFFER_LAST   = (6 * EFFECTIVE_ROW_PIXELS) + 6;
    localparam int unsigned CENTRE_OFFSET = (3 * EFFECTIVE_ROW_PIXELS) + 3;
    localparam int unsigned CENTRE_OFFSET_NEXT = CENTRE_OFFSET + 1;
    localparam int unsigned FILL_W        = $clog2(BUFFER_LAST + 2);

    localparam logic [2:0] kernel_7 [0:48] = '{
        1, 1, 2, 2, 2, 1, 1,
        1, 2, 4, 4, 4, 2, 1,
        2, 4, 4, 4, 4, 4, 2,
        2, 4, 4, 4, 4, 4, 2,
        2, 4, 4, 4, 4, 4, 2,
        1, 2, 4, 4, 4, 2, 1,
        1, 1, 2, 2, 2, 1, 1
    };

    // -------------------------------------------------------------------------
    // Compact valid-only shift buffers for the 120-pixel-wide interior stream.
    // -------------------------------------------------------------------------
    logic [9:0]                   confidence_buffer [0:BUFFER_LAST];
    logic signed [15:0]           disparity_buffer  [0:BUFFER_LAST];
    logic [$clog2(IMAGE_DIM)-1:0] row_buffer        [0:BUFFER_LAST];
    logic [$clog2(IMAGE_DIM)-1:0] column_buffer     [0:BUFFER_LAST];

    logic [FILL_W-1:0] fill_count = '0;
    logic              filled     = 1'b0;

    logic input_in_active_region;

    integer idx;
    integer r_idx;
    integer c_idx;
    integer tap_idx;
    integer buf_idx;

    always_comb begin
        input_in_active_region =
            pixel_valid_in &&
            (row_idx_in    >= FIRST_INPUT_PIXEL) &&
            (row_idx_in    <= LAST_INPUT_PIXEL) &&
            (column_idx_in >= FIRST_INPUT_PIXEL) &&
            (column_idx_in <= LAST_INPUT_PIXEL);
    end

    // -------------------------------------------------------------------------
    // Helper functions
    // -------------------------------------------------------------------------
    function automatic logic [9:0] sat_u10(
        input logic [34:0] x
    );
        begin
            if (x > 35'd1023) begin
                sat_u10 = 10'h3FF;
            end
            else begin
                sat_u10 = x[9:0];
            end
        end
    endfunction

    function automatic logic signed [15:0] sat_s16_from_s35(
        input logic signed [34:0] x
    );
        begin
            if (x > 35'sd32767) begin
                sat_s16_from_s35 = 16'sh7FFF;
            end
            else if (x < -35'sd32768) begin
                sat_s16_from_s35 = 16'sh8000;
            end
            else begin
                sat_s16_from_s35 = x[15:0];
            end
        end
    endfunction

    function automatic logic signed [34:0] round_divide_by_128_s35(
        input logic signed [34:0] x
    );
        begin
            if (x >= 0) begin
                round_divide_by_128_s35 = (x + 35'sd64) / 35'sd128;
            end
            else begin
                round_divide_by_128_s35 = -(((-x) + 35'sd64) / 35'sd128);
            end
        end
    endfunction

    function automatic logic [34:0] zero_extend_conf_tap(
        input logic [9:0] sample,
        input logic [2:0] kernel_weight
    );
        logic [34:0] sample_ext;
        logic [34:0] weight_ext;
        begin
            sample_ext = {25'd0, sample};
            weight_ext = {32'd0, kernel_weight};

            zero_extend_conf_tap = sample_ext * weight_ext;
        end
    endfunction

    function automatic logic signed [34:0] sign_extend_disp_tap(
        input logic signed [15:0] sample,
        input logic [2:0]         kernel_weight
    );
        logic signed [34:0] sample_ext;
        logic signed [34:0] weight_ext;
        begin
            sample_ext = {{19{sample[15]}}, sample};
            weight_ext = $signed({32'd0, kernel_weight});

            sign_extend_disp_tap = sample_ext * weight_ext;
        end
    endfunction

    // -------------------------------------------------------------------------
    // Pipeline metadata
    // -------------------------------------------------------------------------
    logic                    valid_s0 = 1'b0;
    logic                    valid_s1 = 1'b0;
    logic                    valid_s2 = 1'b0;
    logic                    valid_s3 = 1'b0;
    logic                    valid_s4 = 1'b0;
    logic                    valid_s5 = 1'b0;
    logic                    valid_s6 = 1'b0;
    logic                    valid_s7 = 1'b0;

    logic [$clog2(IMAGE_DIM)-1:0] row_s0 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] row_s1 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] row_s2 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] row_s3 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] row_s4 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] row_s5 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] row_s6 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] row_s7 = '0;

    logic [$clog2(IMAGE_DIM)-1:0] column_s0 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] column_s1 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] column_s2 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] column_s3 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] column_s4 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] column_s5 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] column_s6 = '0;
    logic [$clog2(IMAGE_DIM)-1:0] column_s7 = '0;

    // -------------------------------------------------------------------------
    // Registered weighted taps and reduction tree
    // -------------------------------------------------------------------------
    logic [34:0]        conf_tap_s0 [0:48];
    logic signed [34:0] disp_tap_s0 [0:48];

    logic [34:0]        conf_s1 [0:24];
    logic signed [34:0] disp_s1 [0:24];

    logic [34:0]        conf_s2 [0:12];
    logic signed [34:0] disp_s2 [0:12];

    logic [34:0]        conf_s3 [0:6];
    logic signed [34:0] disp_s3 [0:6];

    logic [34:0]        conf_s4 [0:3];
    logic signed [34:0] disp_s4 [0:3];

    logic [34:0]        conf_s5 [0:1];
    logic signed [34:0] disp_s5 [0:1];

    logic [34:0]        conf_sum_s6 = '0;
    logic signed [34:0] disp_sum_s6 = '0;

    logic [34:0]        conf_rounded_s7 = '0;
    logic signed [34:0] disp_rounded_s7 = '0;

    // -------------------------------------------------------------------------
    // Stage 0:
    //   - Shift in only active interior pixels.
    //   - Capture weighted taps from the compact 120-pixel-wide stream.
    //
    // Nonblocking assignments mean the tap reads use the pre-shift buffer state.
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Stage0_Buffer_And_Taps
        // Default: no new Stage-0 output unless a new active input sample arrives.
        valid_s0 <= 1'b0;

        if (input_in_active_region) begin
            // -------------------------------------------------------------
            // Shift in the new active interior sample.
            //
            // The 7x7 window must include the current input sample when the
            // current sample is the bottom-right tap of the window. Because
            // nonblocking assignments read the old buffer values, the tap
            // capture below explicitly reads the POST-shift buffer state:
            //   post_buffer[i] = old_buffer[i+1]
            //   post_buffer[BUFFER_LAST] = current input
            //
            // This avoids losing the final output pixel. If taps are taken
            // from the pre-shift buffer, the last valid centre pixel
            // (row/col 120 for a 7x7 kernel over input 4..123) is never
            // emitted because there is no extra valid sample after (123,123).
            // -------------------------------------------------------------
            for (idx = 0; idx < BUFFER_LAST; idx = idx + 1) begin
                confidence_buffer[idx] <= confidence_buffer[idx + 1];
                disparity_buffer[idx]  <= disparity_buffer[idx + 1];
                row_buffer[idx]        <= row_buffer[idx + 1];
                column_buffer[idx]     <= column_buffer[idx + 1];
            end

            confidence_buffer[BUFFER_LAST] <= confidence_in;
            disparity_buffer[BUFFER_LAST]  <= disparity_in;
            row_buffer[BUFFER_LAST]        <= row_idx_in;
            column_buffer[BUFFER_LAST]     <= column_idx_in;

            if (!filled) begin
                fill_count <= fill_count + {{(FILL_W-1){1'b0}}, 1'b1};

                if (fill_count == BUFFER_LAST[FILL_W-1:0]) begin
                    filled <= 1'b1;
                end
            end

            // Centre metadata from the POST-shift buffer state.
            row_s0    <= row_buffer[CENTRE_OFFSET_NEXT];
            column_s0 <= column_buffer[CENTRE_OFFSET_NEXT];

            // Valid when the current sample completes a full 7x7 window and
            // the post-shift centre coordinate is inside the intended output
            // region: 7..120.
            valid_s0 <=
                (filled || (fill_count == BUFFER_LAST[FILL_W-1:0])) &&
                (row_buffer[CENTRE_OFFSET_NEXT]    >= FIRST_OUTPUT_PIXEL) &&
                (row_buffer[CENTRE_OFFSET_NEXT]    <= LAST_OUTPUT_PIXEL) &&
                (column_buffer[CENTRE_OFFSET_NEXT] >= FIRST_OUTPUT_PIXEL) &&
                (column_buffer[CENTRE_OFFSET_NEXT] <= LAST_OUTPUT_PIXEL);

            for (r_idx = 0; r_idx < 7; r_idx = r_idx + 1) begin
                for (c_idx = 0; c_idx < 7; c_idx = c_idx + 1) begin
                    tap_idx = (r_idx * 7) + c_idx;
                    buf_idx = (r_idx * EFFECTIVE_ROW_PIXELS) + c_idx;

                    if (buf_idx == BUFFER_LAST) begin
                        conf_tap_s0[tap_idx] <= zero_extend_conf_tap(
                            confidence_in,
                            kernel_7[tap_idx]
                        );

                        disp_tap_s0[tap_idx] <= sign_extend_disp_tap(
                            disparity_in,
                            kernel_7[tap_idx]
                        );
                    end
                    else begin
                        conf_tap_s0[tap_idx] <= zero_extend_conf_tap(
                            confidence_buffer[buf_idx + 1],
                            kernel_7[tap_idx]
                        );

                        disp_tap_s0[tap_idx] <= sign_extend_disp_tap(
                            disparity_buffer[buf_idx + 1],
                            kernel_7[tap_idx]
                        );
                    end
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // Stage 1: 49 -> 25
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Stage1_Reduce_49_To_25
        valid_s1  <= valid_s0;
        row_s1    <= row_s0;
        column_s1 <= column_s0;

        for (idx = 0; idx < 24; idx = idx + 1) begin
            conf_s1[idx] <= conf_tap_s0[2*idx] + conf_tap_s0[(2*idx) + 1];
            disp_s1[idx] <= disp_tap_s0[2*idx] + disp_tap_s0[(2*idx) + 1];
        end

        conf_s1[24] <= conf_tap_s0[48];
        disp_s1[24] <= disp_tap_s0[48];
    end

    // -------------------------------------------------------------------------
    // Stage 2: 25 -> 13
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Stage2_Reduce_25_To_13
        valid_s2  <= valid_s1;
        row_s2    <= row_s1;
        column_s2 <= column_s1;

        for (idx = 0; idx < 12; idx = idx + 1) begin
            conf_s2[idx] <= conf_s1[2*idx] + conf_s1[(2*idx) + 1];
            disp_s2[idx] <= disp_s1[2*idx] + disp_s1[(2*idx) + 1];
        end

        conf_s2[12] <= conf_s1[24];
        disp_s2[12] <= disp_s1[24];
    end

    // -------------------------------------------------------------------------
    // Stage 3: 13 -> 7
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Stage3_Reduce_13_To_7
        valid_s3  <= valid_s2;
        row_s3    <= row_s2;
        column_s3 <= column_s2;

        for (idx = 0; idx < 6; idx = idx + 1) begin
            conf_s3[idx] <= conf_s2[2*idx] + conf_s2[(2*idx) + 1];
            disp_s3[idx] <= disp_s2[2*idx] + disp_s2[(2*idx) + 1];
        end

        conf_s3[6] <= conf_s2[12];
        disp_s3[6] <= disp_s2[12];
    end

    // -------------------------------------------------------------------------
    // Stage 4: 7 -> 4
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Stage4_Reduce_7_To_4
        valid_s4  <= valid_s3;
        row_s4    <= row_s3;
        column_s4 <= column_s3;

        for (idx = 0; idx < 3; idx = idx + 1) begin
            conf_s4[idx] <= conf_s3[2*idx] + conf_s3[(2*idx) + 1];
            disp_s4[idx] <= disp_s3[2*idx] + disp_s3[(2*idx) + 1];
        end

        conf_s4[3] <= conf_s3[6];
        disp_s4[3] <= disp_s3[6];
    end

    // -------------------------------------------------------------------------
    // Stage 5: 4 -> 2
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Stage5_Reduce_4_To_2
        valid_s5  <= valid_s4;
        row_s5    <= row_s4;
        column_s5 <= column_s4;

        conf_s5[0] <= conf_s4[0] + conf_s4[1];
        conf_s5[1] <= conf_s4[2] + conf_s4[3];

        disp_s5[0] <= disp_s4[0] + disp_s4[1];
        disp_s5[1] <= disp_s4[2] + disp_s4[3];
    end

    // -------------------------------------------------------------------------
    // Stage 6: 2 -> 1 final sum
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Stage6_Final_Sum
        valid_s6  <= valid_s5;
        row_s6    <= row_s5;
        column_s6 <= column_s5;

        conf_sum_s6 <= conf_s5[0] + conf_s5[1];
        disp_sum_s6 <= disp_s5[0] + disp_s5[1];
    end

    // -------------------------------------------------------------------------
    // Stage 7:
    //   - Divide by 128 using rounded shift.
    //   - Keep this separate from the final sum stage.
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Stage7_Round
        valid_s7  <= valid_s6;
        row_s7    <= row_s6;
        column_s7 <= column_s6;

        conf_rounded_s7 <= (conf_sum_s6 + 35'd64) / 35'd128;
        disp_rounded_s7 <= round_divide_by_128_s35(disp_sum_s6);
    end

    // -------------------------------------------------------------------------
    // Output stage:
    //   - Saturate to original output widths.
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Output_Stage
        pixel_valid_out <= 1'b0;
        solf_out        <= 1'b0;
        eolf_out        <= 1'b0;
        row_idx_out     <= '0;
        column_idx_out  <= '0;
        confidence_out  <= 10'd0;
        disparity_out   <= 16'sd0;

        if (valid_s7) begin
            pixel_valid_out <= 1'b1;
            row_idx_out     <= row_s7;
            column_idx_out  <= column_s7;
            confidence_out  <= sat_u10(conf_rounded_s7);
            disparity_out   <= sat_s16_from_s35(disp_rounded_s7);

            if ((row_s7 == FIRST_OUTPUT_PIXEL) && (column_s7 == FIRST_OUTPUT_PIXEL)) begin
                solf_out <= 1'b1;
            end

            if ((row_s7 == LAST_OUTPUT_PIXEL) && (column_s7 == LAST_OUTPUT_PIXEL)) begin
                eolf_out <= 1'b1;
            end
        end
    end

endmodule