cuda_tile.module @m {
  entry @xattn_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %11 = make_tensor_view %10, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf64, strides=[64, 1]>
    %12 = make_partition_view %11 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19, %20 = load_view_tko weak %12[%13, %18] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %21 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %22 = make_tensor_view %21, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %23 = make_partition_view %22 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %24, %25, %26 = get_tile_block_id : tile<i32>
    %27, %28 = load_view_tko weak %23[%25, %18] token=%20 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %29 = permute %27 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
    %30 = constant <f64: 0.0> : tile<32x32xf64>
    %31 = mmaf %19, %29, %30 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %32 = constant <i32: 2048> : tile<i32>
    %33 = muli %9, %32 : tile<i32>
    %34 = constant <i32: 2048> : tile<i32>
    %35 = muli %1, %34 : tile<i32>
    %36 = addi %33, %35 : tile<i32>
    %37 = constant <i32: 32> : tile<i32>
    %38 = muli %5, %37 : tile<i32>
    %39 = addi %36, %38 : tile<i32>
    %40 = constant <f64: 0.17677669529663687> : tile<32x32xf64>
    %41 = mulf %31, %40 rounding<nearest_even> : tile<32x32xf64>
    %42 = reshape %39 : tile<i32> -> tile<1x1xi32>
    %43 = broadcast %42 : tile<1x1xi32> -> tile<32x32xi32>
    %44 = iota : tile<32xi32>
    %45 = reshape %44 : tile<32xi32> -> tile<32x1xi32>
    %46 = broadcast %45 : tile<32x1xi32> -> tile<32x32xi32>
    %47 = constant <i32: 64> : tile<32x32xi32>
    %48 = muli %46, %47 : tile<32x32xi32>
    %49 = addi %43, %48 : tile<32x32xi32>
    %50 = iota : tile<32xi32>
    %51 = reshape %50 : tile<32xi32> -> tile<1x32xi32>
    %52 = broadcast %51 : tile<1x32xi32> -> tile<32x32xi32>
    %53 = addi %49, %52 : tile<32x32xi32>
    %54 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %55 = broadcast %54 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %56 = offset %55, %53 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %57 = store_ptr_tko weak %56, %41 token=%28 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
