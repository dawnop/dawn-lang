cuda_tile.module @m {
  entry @attn_alibi(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 0> : tile<i32>
    %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %9 = make_tensor_view %8, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %10 = make_partition_view %9 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %11, %12, %13 = get_tile_block_id : tile<i32>
    %14, %15 = load_view_tko weak %10[%11, %7] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %16 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %17 = make_tensor_view %16, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %18 = make_partition_view %17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %19, %20, %21 = get_tile_block_id : tile<i32>
    %22, %23 = load_view_tko weak %18[%20, %7] token=%15 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %24 = permute %22 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
    %25 = constant <f64: 0.0> : tile<32x32xf64>
    %26 = mmaf %14, %24, %25 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %27 = constant <f64: 0.17677669529663687> : tile<32x32xf64>
    %28 = mulf %26, %27 rounding<nearest_even> : tile<32x32xf64>
    %29 = constant <i32: 32> : tile<i32>
    %30 = muli %1, %29 : tile<i32>
    %31 = reshape %30 : tile<i32> -> tile<1x1xi32>
    %32 = broadcast %31 : tile<1x1xi32> -> tile<32x32xi32>
    %33 = iota : tile<32xi32>
    %34 = reshape %33 : tile<32xi32> -> tile<32x1xi32>
    %35 = broadcast %34 : tile<32x1xi32> -> tile<32x32xi32>
    %36 = addi %32, %35 : tile<32x32xi32>
    %37 = iota : tile<32xi32>
    %38 = reshape %37 : tile<32xi32> -> tile<1x32xi32>
    %39 = broadcast %38 : tile<1x32xi32> -> tile<32x32xi32>
    %40 = constant <i32: 0> : tile<32x32xi32>
    %41 = muli %39, %40 : tile<32x32xi32>
    %42 = addi %36, %41 : tile<32x32xi32>
    %43 = constant <i32: 32> : tile<i32>
    %44 = muli %5, %43 : tile<i32>
    %45 = reshape %44 : tile<i32> -> tile<1x1xi32>
    %46 = broadcast %45 : tile<1x1xi32> -> tile<32x32xi32>
    %47 = iota : tile<32xi32>
    %48 = reshape %47 : tile<32xi32> -> tile<32x1xi32>
    %49 = broadcast %48 : tile<32x1xi32> -> tile<32x32xi32>
    %50 = constant <i32: 0> : tile<32x32xi32>
    %51 = muli %49, %50 : tile<32x32xi32>
    %52 = addi %46, %51 : tile<32x32xi32>
    %53 = iota : tile<32xi32>
    %54 = reshape %53 : tile<32xi32> -> tile<1x32xi32>
    %55 = broadcast %54 : tile<1x32xi32> -> tile<32x32xi32>
    %56 = addi %52, %55 : tile<32x32xi32>
    %57 = subi %42, %56 : tile<32x32xi32>
    %58 = itof %57 signed rounding<nearest_even> : tile<32x32xi32> -> tile<32x32xf64>
    %59 = constant <f64: -0.125> : tile<32x32xf64>
    %60 = mulf %59, %58 rounding<nearest_even> : tile<32x32xf64>
    %61 = addf %28, %60 rounding<nearest_even> : tile<32x32xf64>
    %62 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %63 = make_tensor_view %62, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %64 = make_partition_view %63 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %65 = store_view_tko weak %61, %64[%11, %20] token=%23 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
