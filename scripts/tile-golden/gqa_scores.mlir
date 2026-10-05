cuda_tile.module @m {
  entry @gqa_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 2> : tile<i32>
    %5 = muli %3, %4 : tile<i32>
    %6, %7, %8 = get_tile_block_id : tile<i32>
    %9 = addi %5, %6 : tile<i32>
    %10 = constant <i32: 2048> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = reshape %11 : tile<i32> -> tile<1x1xi32>
    %13 = broadcast %12 : tile<1x1xi32> -> tile<64x32xi32>
    %14 = iota : tile<64xi32>
    %15 = reshape %14 : tile<64xi32> -> tile<64x1xi32>
    %16 = broadcast %15 : tile<64x1xi32> -> tile<64x32xi32>
    %17 = constant <i32: 32> : tile<64x32xi32>
    %18 = muli %16, %17 : tile<64x32xi32>
    %19 = addi %13, %18 : tile<64x32xi32>
    %20 = iota : tile<32xi32>
    %21 = reshape %20 : tile<32xi32> -> tile<1x32xi32>
    %22 = broadcast %21 : tile<1x32xi32> -> tile<64x32xi32>
    %23 = addi %19, %22 : tile<64x32xi32>
    %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %25 = broadcast %24 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %26 = offset %25, %23 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %27, %28 = load_ptr_tko weak %26 token=%0 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %29 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [128, 32], strides = [32, 1] : tensor_view<128x32xf64, strides=[32, 1]>
    %31 = make_partition_view %30 : partition_view<tile=(64x32), padding_value = zero, tensor_view<128x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %32, %33, %34 = get_tile_block_id : tile<i32>
    %35, %36, %37 = get_tile_block_id : tile<i32>
    %38, %39 = load_view_tko weak %31[%34, %36] token=%28 : partition_view<tile=(64x32), padding_value = zero, tensor_view<128x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x32xf64>, token
    %40 = permute %38 [1, 0] : tile<64x32xf64> -> tile<32x64xf64>
    %41 = constant <f64: 0.0> : tile<64x64xf64>
    %42 = mmaf %27, %40, %41 : tile<64x32xf64>, tile<32x64xf64>, tile<64x64xf64>
    %43 = constant <f64: 0.17677669529663687> : tile<64x64xf64>
    %44 = mulf %42, %43 rounding<nearest_even> : tile<64x64xf64>
    %45 = reshape %44 : tile<64x64xf64> -> tile<1x64x64xf64>
    %46 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %47 = make_tensor_view %46, shape = [2, 128, 64], strides = [8192, 64, 1] : tensor_view<2x128x64xf64, strides=[8192, 64, 1]>
    %48 = make_partition_view %47 : partition_view<tile=(1x64x64), padding_value = zero, tensor_view<2x128x64xf64, strides=[8192, 64, 1]>, dim_map=[0, 1, 2]>
    %49, %50, %51 = get_tile_block_id : tile<i32>
    %52 = store_view_tko weak %45, %48[%34, %49, %36] token=%39 : tile<1x64x64xf64>, partition_view<tile=(1x64x64), padding_value = zero, tensor_view<2x128x64xf64, strides=[8192, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
