cuda_tile.module @m {
  entry @dtype_i16(%arg0: tile<ptr<i16>>, %arg1: tile<ptr<i16>>, %arg2: tile<ptr<i16>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i16>>
    %7 = make_tensor_view %6, shape = [512], strides = [1] : tensor_view<512xi16, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi16, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi16, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi16>, token
    %14 = assume div_by<16>, %arg1 : tile<ptr<i16>>
    %15 = make_tensor_view %14, shape = [512], strides = [1] : tensor_view<512xi16, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi16, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%9] token=%13 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi16, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi16>, token
    %19 = constant <i32: 0> : tile<i32>
    %20 = addi %5, %19 : tile<i32>
    %21 = addi %12, %17 : tile<128xi16>
    %22 = reshape %20 : tile<i32> -> tile<1xi32>
    %23 = broadcast %22 : tile<1xi32> -> tile<128xi32>
    %24 = iota : tile<128xi32>
    %25 = addi %23, %24 : tile<128xi32>
    %26 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %27 = broadcast %26 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %28 = offset %27, %25 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %29 = store_ptr_tko weak %28, %21 token=%18 : tile<128xptr<i16>>, tile<128xi16> -> token
    %30 = constant <i32: 512> : tile<i32>
    %31 = addi %5, %30 : tile<i32>
    %32 = subi %12, %17 : tile<128xi16>
    %33 = reshape %31 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<128xi32>
    %35 = iota : tile<128xi32>
    %36 = addi %34, %35 : tile<128xi32>
    %37 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %38 = broadcast %37 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %39 = offset %38, %36 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %40 = store_ptr_tko weak %39, %32 token=%29 : tile<128xptr<i16>>, tile<128xi16> -> token
    %41 = constant <i32: 1024> : tile<i32>
    %42 = addi %5, %41 : tile<i32>
    %43 = muli %12, %17 : tile<128xi16>
    %44 = reshape %42 : tile<i32> -> tile<1xi32>
    %45 = broadcast %44 : tile<1xi32> -> tile<128xi32>
    %46 = iota : tile<128xi32>
    %47 = addi %45, %46 : tile<128xi32>
    %48 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %49 = broadcast %48 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %50 = offset %49, %47 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %51 = store_ptr_tko weak %50, %43 token=%40 : tile<128xptr<i16>>, tile<128xi16> -> token
    %52 = constant <i32: 1536> : tile<i32>
    %53 = addi %5, %52 : tile<i32>
    %54 = constant <i16: 3> : tile<128xi16>
    %55 = shli %12, %54 : tile<128xi16>
    %56 = constant <i16: 2> : tile<128xi16>
    %57 = shri %55, %56 signed : tile<128xi16>
    %58 = reshape %53 : tile<i32> -> tile<1xi32>
    %59 = broadcast %58 : tile<1xi32> -> tile<128xi32>
    %60 = iota : tile<128xi32>
    %61 = addi %59, %60 : tile<128xi32>
    %62 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %63 = broadcast %62 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %64 = offset %63, %61 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %65 = store_ptr_tko weak %64, %57 token=%51 : tile<128xptr<i16>>, tile<128xi16> -> token
    %66 = constant <i32: 2048> : tile<i32>
    %67 = addi %5, %66 : tile<i32>
    %68 = itof %12 signed rounding<nearest_even> : tile<128xi16> -> tile<128xf64>
    %69 = ftoi %68 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi16>
    %70 = reshape %67 : tile<i32> -> tile<1xi32>
    %71 = broadcast %70 : tile<1xi32> -> tile<128xi32>
    %72 = iota : tile<128xi32>
    %73 = addi %71, %72 : tile<128xi32>
    %74 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %75 = broadcast %74 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %76 = offset %75, %73 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %77 = store_ptr_tko weak %76, %69 token=%65 : tile<128xptr<i16>>, tile<128xi16> -> token
    return
  }
}
