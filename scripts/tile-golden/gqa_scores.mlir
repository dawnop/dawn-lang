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
    %43 = constant <i32: 4096> : tile<i32>
    %44 = muli %9, %43 : tile<i32>
    %45 = constant <f64: 0.17677669529663687> : tile<64x64xf64>
    %46 = mulf %42, %45 rounding<nearest_even> : tile<64x64xf64>
    %47 = reshape %44 : tile<i32> -> tile<1x1xi32>
    %48 = broadcast %47 : tile<1x1xi32> -> tile<64x64xi32>
    %49 = iota : tile<64xi32>
    %50 = reshape %49 : tile<64xi32> -> tile<64x1xi32>
    %51 = broadcast %50 : tile<64x1xi32> -> tile<64x64xi32>
    %52 = constant <i32: 64> : tile<64x64xi32>
    %53 = muli %51, %52 : tile<64x64xi32>
    %54 = addi %48, %53 : tile<64x64xi32>
    %55 = iota : tile<64xi32>
    %56 = reshape %55 : tile<64xi32> -> tile<1x64xi32>
    %57 = broadcast %56 : tile<1x64xi32> -> tile<64x64xi32>
    %58 = addi %54, %57 : tile<64x64xi32>
    %59 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %60 = broadcast %59 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %61 = offset %60, %58 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %62 = store_ptr_tko weak %61, %46 token=%39 : tile<64x64xptr<f64>>, tile<64x64xf64> -> token
    return
  }
}
