cuda_tile.module @m {
  entry @dtype_i64(%arg0: tile<ptr<i64>>, %arg1: tile<ptr<i64>>, %arg2: tile<ptr<i64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i64>>
    %7 = make_tensor_view %6, shape = [512], strides = [1] : tensor_view<512xi64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi64>, token
    %14 = assume div_by<16>, %arg1 : tile<ptr<i64>>
    %15 = make_tensor_view %14, shape = [512], strides = [1] : tensor_view<512xi64, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi64, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%9] token=%13 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi64>, token
    %19 = constant <i32: 0> : tile<i32>
    %20 = addi %5, %19 : tile<i32>
    %21 = addi %12, %17 : tile<128xi64>
    %22 = reshape %20 : tile<i32> -> tile<1xi32>
    %23 = broadcast %22 : tile<1xi32> -> tile<128xi32>
    %24 = iota : tile<128xi32>
    %25 = addi %23, %24 : tile<128xi32>
    %26 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %27 = broadcast %26 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %28 = offset %27, %25 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %29 = store_ptr_tko weak %28, %21 token=%18 : tile<128xptr<i64>>, tile<128xi64> -> token
    %30 = constant <i32: 512> : tile<i32>
    %31 = addi %5, %30 : tile<i32>
    %32 = subi %12, %17 : tile<128xi64>
    %33 = reshape %31 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<128xi32>
    %35 = iota : tile<128xi32>
    %36 = addi %34, %35 : tile<128xi32>
    %37 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %38 = broadcast %37 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %39 = offset %38, %36 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %40 = store_ptr_tko weak %39, %32 token=%29 : tile<128xptr<i64>>, tile<128xi64> -> token
    %41 = constant <i32: 1024> : tile<i32>
    %42 = addi %5, %41 : tile<i32>
    %43 = muli %12, %17 : tile<128xi64>
    %44 = reshape %42 : tile<i32> -> tile<1xi32>
    %45 = broadcast %44 : tile<1xi32> -> tile<128xi32>
    %46 = iota : tile<128xi32>
    %47 = addi %45, %46 : tile<128xi32>
    %48 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %49 = broadcast %48 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %50 = offset %49, %47 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %51 = store_ptr_tko weak %50, %43 token=%40 : tile<128xptr<i64>>, tile<128xi64> -> token
    %52 = constant <i32: 1536> : tile<i32>
    %53 = addi %5, %52 : tile<i32>
    %54 = constant <i64: 4294967296> : tile<128xi64>
    %55 = addi %12, %54 : tile<128xi64>
    %56 = reshape %53 : tile<i32> -> tile<1xi32>
    %57 = broadcast %56 : tile<1xi32> -> tile<128xi32>
    %58 = iota : tile<128xi32>
    %59 = addi %57, %58 : tile<128xi32>
    %60 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %61 = broadcast %60 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %62 = offset %61, %59 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %63 = store_ptr_tko weak %62, %55 token=%51 : tile<128xptr<i64>>, tile<128xi64> -> token
    %64 = constant <i32: 2048> : tile<i32>
    %65 = addi %5, %64 : tile<i32>
    %66 = itof %12 signed rounding<nearest_even> : tile<128xi64> -> tile<128xf64>
    %67 = ftoi %66 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi64>
    %68 = reshape %65 : tile<i32> -> tile<1xi32>
    %69 = broadcast %68 : tile<1xi32> -> tile<128xi32>
    %70 = iota : tile<128xi32>
    %71 = addi %69, %70 : tile<128xi32>
    %72 = reshape %arg2 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %73 = broadcast %72 : tile<1xptr<i64>> -> tile<128xptr<i64>>
    %74 = offset %73, %71 : tile<128xptr<i64>>, tile<128xi32> -> tile<128xptr<i64>>
    %75 = store_ptr_tko weak %74, %67 token=%63 : tile<128xptr<i64>>, tile<128xi64> -> token
    return
  }
}
