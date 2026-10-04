cuda_tile.module @m {
  entry @llama_rope(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_num_tile_blocks : tile<i32>
    %5 = constant <i32: 64> : tile<i32>
    %6 = muli %3, %5 : tile<i32>
    %7 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %8 = make_tensor_view %7, shape = [%6, 32], strides = [32, 1] : tile<i32> -> tensor_view<?x32xf64, strides=[32, 1]>
    %9 = make_partition_view %8 : partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %9[%11, %1] token=%0 : partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x16xf64>, token
    %15 = constant <i32: 1> : tile<i32>
    %16, %17 = load_view_tko weak %9[%11, %15] token=%14 : partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x16xf64>, token
    %18 = constant <i32: 0> : tile<i32>
    %19 = constant <i32: 0> : tile<i32>
    %20 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %21 = make_tensor_view %20, shape = [64, 16], strides = [16, 1] : tensor_view<64x16xf64, strides=[16, 1]>
    %22 = make_partition_view %21 : partition_view<tile=(64x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %23, %24 = load_view_tko weak %22[%18, %19] token=%17 : partition_view<tile=(64x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x16xf64>, token
    %25 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %26 = make_tensor_view %25, shape = [64, 16], strides = [16, 1] : tensor_view<64x16xf64, strides=[16, 1]>
    %27 = make_partition_view %26 : partition_view<tile=(64x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %28, %29 = load_view_tko weak %27[%18, %19] token=%24 : partition_view<tile=(64x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x16xf64>, token
    %30, %31, %32 = get_tile_block_id : tile<i32>
    %33 = constant <i32: 2048> : tile<i32>
    %34 = muli %31, %33 : tile<i32>
    %35 = mulf %13, %23 rounding<nearest_even> : tile<64x16xf64>
    %36 = mulf %16, %28 rounding<nearest_even> : tile<64x16xf64>
    %37 = subf %35, %36 rounding<nearest_even> : tile<64x16xf64>
    %38 = reshape %34 : tile<i32> -> tile<1x1xi32>
    %39 = broadcast %38 : tile<1x1xi32> -> tile<64x16xi32>
    %40 = iota : tile<64xi32>
    %41 = reshape %40 : tile<64xi32> -> tile<64x1xi32>
    %42 = broadcast %41 : tile<64x1xi32> -> tile<64x16xi32>
    %43 = constant <i32: 32> : tile<64x16xi32>
    %44 = muli %42, %43 : tile<64x16xi32>
    %45 = addi %39, %44 : tile<64x16xi32>
    %46 = iota : tile<16xi32>
    %47 = reshape %46 : tile<16xi32> -> tile<1x16xi32>
    %48 = broadcast %47 : tile<1x16xi32> -> tile<64x16xi32>
    %49 = addi %45, %48 : tile<64x16xi32>
    %50 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %51 = broadcast %50 : tile<1x1xptr<f64>> -> tile<64x16xptr<f64>>
    %52 = offset %51, %49 : tile<64x16xptr<f64>>, tile<64x16xi32> -> tile<64x16xptr<f64>>
    %53 = store_ptr_tko weak %52, %37 token=%29 : tile<64x16xptr<f64>>, tile<64x16xf64> -> token
    %54 = constant <i32: 16> : tile<i32>
    %55 = addi %34, %54 : tile<i32>
    %56 = mulf %13, %28 rounding<nearest_even> : tile<64x16xf64>
    %57 = mulf %16, %23 rounding<nearest_even> : tile<64x16xf64>
    %58 = addf %56, %57 rounding<nearest_even> : tile<64x16xf64>
    %59 = reshape %55 : tile<i32> -> tile<1x1xi32>
    %60 = broadcast %59 : tile<1x1xi32> -> tile<64x16xi32>
    %61 = iota : tile<64xi32>
    %62 = reshape %61 : tile<64xi32> -> tile<64x1xi32>
    %63 = broadcast %62 : tile<64x1xi32> -> tile<64x16xi32>
    %64 = constant <i32: 32> : tile<64x16xi32>
    %65 = muli %63, %64 : tile<64x16xi32>
    %66 = addi %60, %65 : tile<64x16xi32>
    %67 = iota : tile<16xi32>
    %68 = reshape %67 : tile<16xi32> -> tile<1x16xi32>
    %69 = broadcast %68 : tile<1x16xi32> -> tile<64x16xi32>
    %70 = addi %66, %69 : tile<64x16xi32>
    %71 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %72 = broadcast %71 : tile<1x1xptr<f64>> -> tile<64x16xptr<f64>>
    %73 = offset %72, %70 : tile<64x16xptr<f64>>, tile<64x16xi32> -> tile<64x16xptr<f64>>
    %74 = store_ptr_tko weak %73, %58 token=%53 : tile<64x16xptr<f64>>, tile<64x16xf64> -> token
    return
  }
}
