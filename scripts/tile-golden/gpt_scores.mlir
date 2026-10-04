cuda_tile.module @m {
  entry @gpt_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %5 = make_tensor_view %4, shape = [64, 192], strides = [192, 1] : tensor_view<64x192xf64, strides=[192, 1]>
    %6 = make_partition_view %5 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %6[%7, %3] token=%0 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
    %12 = constant <i32: 2> : tile<i32>
    %13 = addi %12, %3 : tile<i32>
    %14, %15 = load_view_tko weak %6[%7, %13] token=%11 : partition_view<tile=(64x32), padding_value = zero, tensor_view<64x192xf64, strides=[192, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
    %16 = permute %14 [1, 0] : tile<64x32xf64> -> tile<32x64xf64>
    %17 = constant <f64: 0.0> : tile<64x64xf64>
    %18 = mmaf %10, %16, %17 : tile<64x32xf64>, tile<32x64xf64>, tile<64x64xf64>
    %19 = constant <i32: 4096> : tile<i32>
    %20 = muli %3, %19 : tile<i32>
    %21 = constant <f64: 0.17677669529663687> : tile<64x64xf64>
    %22 = mulf %18, %21 rounding<nearest_even> : tile<64x64xf64>
    %23 = reshape %20 : tile<i32> -> tile<1x1xi32>
    %24 = broadcast %23 : tile<1x1xi32> -> tile<64x64xi32>
    %25 = iota : tile<64xi32>
    %26 = reshape %25 : tile<64xi32> -> tile<64x1xi32>
    %27 = broadcast %26 : tile<64x1xi32> -> tile<64x64xi32>
    %28 = constant <i32: 64> : tile<64x64xi32>
    %29 = muli %27, %28 : tile<64x64xi32>
    %30 = addi %24, %29 : tile<64x64xi32>
    %31 = iota : tile<64xi32>
    %32 = reshape %31 : tile<64xi32> -> tile<1x64xi32>
    %33 = broadcast %32 : tile<1x64xi32> -> tile<64x64xi32>
    %34 = addi %30, %33 : tile<64x64xi32>
    %35 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %36 = broadcast %35 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %37 = offset %36, %34 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %38 = store_ptr_tko weak %37, %22 token=%15 : tile<64x64xptr<f64>>, tile<64x64xf64> -> token
    return
  }
}
